"""
Processing an upload (run by the Celery task in src/api/worker/tasks.py; free of Celery itself).

    queued -> predicting (CSV) / converting (PCAP, Stage D) -> completed | failed

The CSV is read in batches of BATCH_ROWS. Each batch is predicted and appended to
<results_dir>/<upload_id>/flows.parquet:
- `row` (0-based, the id the results endpoints use);
- metadata (Flow ID, IPs, ports, timestamp) and the uploaded `Label`, when present;
- the prediction columns;
- the model input features, which explanations need later.
A summary row goes to prediction_summaries.

An upload can be deleted while it is processed: every progress update and the final write
check deleted_at, and a deleted upload's results are thrown away.
"""

import logging
import os
import re
import shutil
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from src.api.db.models import ModelVersion, PredictionSummary, Upload
from src.api.settings import Settings
from src.api.uploads.service import raw_path, results_dir
from src.inference.engine import InferenceEngine
from src.inference.manager import ModelManager
from src.inference.schema import LABEL_COLUMN, METADATA_COLUMNS

log = logging.getLogger(__name__)

BATCH_ROWS = 50_000
RESULTS_FILE = "flows.parquet"
PREDICTION_COLUMNS = {
    "decision": pa.string(), "reason": pa.string(), "predicted_class": pa.int64(), "class_name": pa.string(),
    "confidence": pa.float64(), "attack_score": pa.float64(), "anomaly_score": pa.float64(),
    "imputed_cells": pa.int64(),
}
FINISHED = ("completed", "failed")


class ProcessingError(Exception):
    """An expected failure; the message is shown to the user."""


class UploadGone(Exception):
    """The upload was deleted while it was processed."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite returns naive datetimes


def _label_key(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


# ── state changes (each its own short transaction, so readers see progress) ──

def _set_progress(session_factory: sessionmaker[Session], upload_id: uuid.UUID, progress: int) -> None:
    with session_factory() as db:
        changed = db.execute(update(Upload)
                             .where(Upload.id == upload_id, Upload.deleted_at.is_(None))
                             .values(progress=progress)).rowcount
        db.commit()
    if not changed:
        raise UploadGone


def mark_failed(session_factory: sessionmaker[Session], settings: Settings, upload_id: uuid.UUID,
                message: str) -> None:
    """Record a failure and drop partial results; a completed upload is left alone."""
    with session_factory() as db:
        upload = db.get(Upload, upload_id)
        if upload is not None and upload.status != "completed":
            now = _now()
            upload.status, upload.error, upload.finished_at = "failed", message[:2000], now
            if upload.started_at is not None:
                upload.processing_ms = int((now - _aware(upload.started_at)).total_seconds() * 1000)
            db.commit()
    shutil.rmtree(results_dir(settings, upload_id), ignore_errors=True)


# ── the job ──

class _Summary:
    def __init__(self, engine: InferenceEngine):
        manifest = engine.bundle.manifest
        self.benign_names = {"benign", _label_key(manifest["class_names"][str(manifest["benign_class"])])}
        self.decisions = Counter()
        self.known_attacks = Counter()
        self.labelled = self.agreeing = 0
        self.inference_ms = 0.0

    def add(self, result: pd.DataFrame, label: pd.Series | None):
        self.decisions.update(result["decision"])
        self.known_attacks.update(result.loc[result["decision"] == "known_attack", "class_name"])
        if label is not None:
            # Attack vs benign agreement: label spellings differ between tools ("BENIGN", "Benign", ...),
            # attack names more so, but "is this flow benign?" compares cleanly
            keys = label.map(_label_key)
            present = label.notna() & (keys != "")
            agree = keys.isin(self.benign_names).to_numpy() == (result["decision"] == "benign").to_numpy()
            self.labelled += int(present.sum())
            self.agreeing += int((agree & present.to_numpy()).sum())


def _schema(engine: InferenceEngine, metadata: list[str], has_label: bool) -> pa.Schema:
    fields = [("row", pa.int64())] + [(c, pa.string()) for c in metadata]
    if has_label:
        fields.append((LABEL_COLUMN, pa.string()))
    fields += list(PREDICTION_COLUMNS.items())
    fields += [(f, pa.float64()) for f in engine.required]
    return pa.schema(fields)


def _results_table(schema: pa.Schema, first_row: int, prepared, result: pd.DataFrame) -> pa.Table:
    n = len(result)
    frame = {"row": np.arange(first_row, first_row + n, dtype=np.int64)}
    for name in schema.names:
        if name == "row":
            continue
        if name == LABEL_COLUMN:
            frame[name] = prepared.label.astype("string").to_numpy(dtype=object, na_value=None)
        elif name in PREDICTION_COLUMNS:
            frame[name] = result[name].to_numpy()
        elif name in prepared.features.columns:
            frame[name] = prepared.features[name].to_numpy(dtype=np.float64)
        else:  # metadata
            frame[name] = prepared.metadata[name].astype("string").to_numpy(dtype=object, na_value=None)
    return pa.Table.from_pydict(frame, schema=schema)


def _count_rows(path) -> int:
    """Data lines (minus the header), for progress; quoted newlines don't occur in flow CSVs."""
    lines, last = 0, b"\n"
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            lines += block.count(b"\n")
            last = block[-1:]
    return max(lines - 1 + (last != b"\n"), 0)


def _predict_csv(upload_id, path, out_dir, engine: InferenceEngine, session_factory) -> tuple[int, _Summary]:
    total = _count_rows(path)
    summary, done, writer = _Summary(engine), 0, None
    partial = out_dir / (RESULTS_FILE + ".part")
    out_dir.mkdir(parents=True, exist_ok=True)
    # Intake checked the first 64 KB is UTF-8; a stray byte further down (often in Label) isn't worth failing for
    csv_options = {"encoding": "utf-8-sig", "encoding_errors": "replace", "skipinitialspace": True}
    try:
        # The active bundle may have changed since the upload was checked
        missing = engine.missing_features(pd.read_csv(path, nrows=0, **csv_options).columns)
        if missing:
            raise ProcessingError(f"{len(missing)} required feature(s) missing: {', '.join(missing)}")
        with pd.read_csv(path, chunksize=BATCH_ROWS, **csv_options) as reader:
            for chunk in reader:
                start = time.perf_counter()
                prepared = engine.prepare(chunk)
                result = engine.predict_prepared(prepared)
                summary.inference_ms += (time.perf_counter() - start) * 1000
                summary.add(result, prepared.label)

                if writer is None:
                    metadata = [c for c in prepared.metadata.columns if c not in engine.required]
                    schema = _schema(engine, metadata, prepared.label is not None)
                    writer = pq.ParquetWriter(partial, schema, compression="zstd")
                writer.write_table(_results_table(writer.schema, done, prepared, result))
                done += len(result)
                _set_progress(session_factory, upload_id, min(99, 100 * done // max(total, 1)))
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as e:
        raise ProcessingError(f"Could not read the CSV after {done:,} flows: {e}")
    finally:
        if writer is not None:
            writer.close()

    if done == 0:
        partial.unlink(missing_ok=True)
        raise ProcessingError("The CSV contains no flows")
    os.replace(partial, out_dir / RESULTS_FILE)
    return done, summary


def process_upload(upload_id: uuid.UUID, models: ModelManager, settings: Settings,
                   session_factory: sessionmaker[Session]) -> str:
    """Process one upload. Returns its final status, or 'skipped' (missing, deleted, already done)."""
    with session_factory() as db:
        upload = db.get(Upload, upload_id)
        if upload is None or upload.deleted_at is not None or upload.status in FINISHED:
            return "skipped"
        file_type, path = upload.file_type, raw_path(settings, upload)
        # A redelivered job (worker died mid-way) finds "predicting" and simply starts over
        upload.status = "predicting" if file_type == "csv" else "converting"
        upload.started_at, upload.progress, upload.error = _now(), 0, None
        db.commit()

    clock, out_dir = time.monotonic(), results_dir(settings, upload_id)
    try:
        if file_type != "csv":
            raise ProcessingError("PCAP processing is not available yet (the flow extractor is still being validated)")
        if not path.exists():
            raise ProcessingError("The uploaded file is no longer available")
        models.ensure_current()
        engine = models.engine()          # one engine for the whole job, even if a switch happens meanwhile
        if engine is None:
            raise ProcessingError("No active model bundle. An admin must activate one.")

        n_flows, summary = _predict_csv(upload_id, path, out_dir, engine, session_factory)

        with session_factory() as db:
            version_id = db.scalar(select(ModelVersion.id).where(ModelVersion.bundle_id == engine.bundle.bundle_id))
            finished = db.execute(
                update(Upload).where(Upload.id == upload_id, Upload.deleted_at.is_(None))
                .values(status="completed", progress=100, n_flows=n_flows, finished_at=_now(),
                        processing_ms=int((time.monotonic() - clock) * 1000), model_version_id=version_id)
            ).rowcount
            if not finished:
                raise UploadGone
            row = db.get(PredictionSummary, upload_id) or PredictionSummary(upload_id=upload_id)
            row.n_benign = summary.decisions["benign"]
            row.n_known_attack = summary.decisions["known_attack"]
            row.n_unknown = summary.decisions["unknown"]
            row.attack_breakdown = dict(summary.known_attacks.most_common())
            row.label_agreement = summary.agreeing / summary.labelled if summary.labelled else None
            row.inference_ms = round(summary.inference_ms, 1)
            db.add(row)
            db.commit()
        log.info("Upload %s: %d flows with %s in %.1f s", upload_id, n_flows, engine.bundle.bundle_id,
                 time.monotonic() - clock)
        return "completed"
    except ProcessingError as e:
        mark_failed(session_factory, settings, upload_id, str(e))
        return "failed"
    except UploadGone:
        shutil.rmtree(out_dir, ignore_errors=True)
        log.info("Upload %s was deleted while processing; results discarded", upload_id)
        return "skipped"


# ── retention ──

def purge_old_uploads(session_factory: sessionmaker[Session], settings: Settings,
                      now: datetime | None = None) -> int:
    """Delete raw files of finished uploads older than retention_days. Results and rows stay."""
    now = now or _now()
    cutoff = now - timedelta(days=settings.retention_days)
    purged = 0
    with session_factory() as db:
        uploads = db.scalars(select(Upload).where(Upload.raw_deleted_at.is_(None), Upload.created_at < cutoff,
                                                  Upload.status.in_(FINISHED))).all()
        for upload in uploads:
            try:
                raw_path(settings, upload).unlink(missing_ok=True)
            except OSError as e:
                log.warning("Retention: could not delete %s: %s", upload.stored_path, e)
                continue
            upload.raw_deleted_at = now
            purged += 1
        db.commit()
    log.info("Retention: deleted %d raw upload(s) older than %d days", purged, settings.retention_days)
    return purged
