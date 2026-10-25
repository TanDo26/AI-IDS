"""
Upload processing: the Celery task, Parquet results, summaries, failures, deletion mid-job, retention.
"""

import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from src.api.db.models import ModelVersion, PredictionSummary, Upload
from src.api.db.session import get_sessionmaker
from src.api.settings import get_settings
from src.api.uploads import processing, service
from src.api.worker import tasks
from tests.conftest import TINY_A
from tests.helpers import API, bearer, flows_csv, upload_file
from tests.tiny_bundle import CANONICAL_FLOWS, FEATURES

EXPECTED = [(decision, reason, cls) for _, decision, reason, cls in CANONICAL_FLOWS.values()]


@pytest.fixture
def uploaded(client, user, active_bundle, queued_jobs):
    """uploaded(content=None) -> upload id, queued for processing."""
    def make(content=None, **kwargs) -> str:
        r = upload_file(client, user, content if content is not None else flows_csv(), **kwargs)
        assert r.status_code == 201, r.text
        return r.json()["id"]
    return make


def row(db, upload_id) -> Upload:
    db.expire_all()
    return db.get(Upload, uuid.UUID(upload_id))


def results(settings, upload_id) -> pd.DataFrame:
    return pd.read_parquet(settings.results_dir / upload_id / processing.RESULTS_FILE)


def raw_file(settings, db, upload_id):
    return service.raw_path(settings, row(db, upload_id))


# ── a successful job ────────────────────────────────────────

def test_upload_is_queued_then_completed(client, user, uploaded, queued_jobs, run_queued, db):
    upload_id = uploaded()
    assert queued_jobs == [upload_id]
    assert run_queued() == ["completed"]

    body = client.get(f"{API}/uploads/{upload_id}", headers=bearer(user)).json()
    assert (body["status"], body["progress"], body["n_flows"], body["error"]) == ("completed", 100, 4, None)
    assert body["started_at"] and body["finished_at"] and body["processing_ms"] >= 0
    active = db.scalar(select(ModelVersion).where(ModelVersion.bundle_id == TINY_A))
    assert body["model_version_id"] == active.id


def test_results_parquet(uploaded, run_queued, settings):
    upload_id = uploaded()
    run_queued()
    df = results(settings, upload_id)
    assert df["row"].tolist() == [0, 1, 2, 3]
    assert list(zip(df["decision"], df["reason"], df["predicted_class"])) == EXPECTED
    assert df["class_name"].tolist() == ["Benign", "DDoS", "PortScan", "Benign"]
    assert (df["Src IP"] == "10.0.0.1").all()
    # The model input features are kept for explanations, unchanged
    inputs = pd.DataFrame([f for f, *_ in CANONICAL_FLOWS.values()])
    required = [f for f in FEATURES if f in df.columns]
    assert len(required) == 6 and "Bwd PSH Flags" not in df.columns   # dropped by the bundle's selector
    np.testing.assert_allclose(df[required].to_numpy(), inputs[required].to_numpy())
    assert not (settings.results_dir / upload_id / (processing.RESULTS_FILE + ".part")).exists()


def test_summary(uploaded, run_queued, db):
    upload_id = uploaded()
    run_queued()
    summary = db.get(PredictionSummary, uuid.UUID(upload_id))
    assert (summary.n_benign, summary.n_known_attack, summary.n_unknown) == (1, 1, 2)
    assert summary.attack_breakdown == {"DDoS": 1}
    assert summary.label_agreement is None and summary.inference_ms > 0


def test_label_agreement_is_attack_vs_benign(uploaded, run_queued, settings, db):
    # decisions: benign, known_attack, unknown, unknown -> the last disagrees with its BENIGN label
    upload_id = uploaded(flows_csv(label=["BENIGN", "DDoS", "PortScan", "benign "]))
    run_queued()
    assert db.get(PredictionSummary, uuid.UUID(upload_id)).label_agreement == pytest.approx(0.75)
    assert results(settings, upload_id)["Label"].tolist() == ["BENIGN", "DDoS", "PortScan", "benign "]


def test_many_batches_with_progress(uploaded, run_queued, settings, monkeypatch):
    monkeypatch.setattr(processing, "BATCH_ROWS", 3)
    seen = []
    original = processing._set_progress
    monkeypatch.setattr(processing, "_set_progress", lambda f, i, p: (seen.append(p), original(f, i, p)))
    upload_id = uploaded(flows_csv(n_copies=5))
    run_queued()

    df = results(settings, upload_id)
    assert df["row"].tolist() == list(range(20))
    assert list(zip(df["decision"], df["reason"], df["predicted_class"])) == EXPECTED * 5
    assert len(seen) == 7 and seen == sorted(seen) and seen[-1] == 99


def test_unusable_values_are_imputed(uploaded, run_queued, settings):
    content = flows_csv().replace(b"20000.0", b"Infinity", 1)   # the benign flow's Flow Bytes/s
    upload_id = uploaded(content)
    run_queued()
    df = results(settings, upload_id)
    assert df.loc[0, "imputed_cells"] == 1 and np.isnan(df.loc[0, "Flow Bytes/s"])


def test_running_twice_does_nothing_more(uploaded, queued_jobs, run_queued, db):
    upload_id = uploaded()
    queued_jobs.append(upload_id)                    # delivered twice
    assert run_queued() == ["completed", "skipped"]


def test_redelivered_after_a_crash(uploaded, run_queued, db):
    upload_id = uploaded()
    db.execute(update(Upload).where(Upload.id == uuid.UUID(upload_id)).values(status="predicting", progress=40))
    db.commit()
    assert run_queued() == ["completed"]


# ── expected failures ───────────────────────────────────────

def failed_with(db, settings, upload_id, text):
    upload = row(db, upload_id)
    assert upload.status == "failed" and text in upload.error, upload.error
    assert upload.finished_at is not None
    assert not (settings.results_dir / upload_id).exists()
    assert db.get(PredictionSummary, uuid.UUID(upload_id)) is None


def test_missing_features_at_processing_time(uploaded, run_queued, settings, db):
    upload_id = uploaded()
    # The active bundle changed, or the file did: the worker checks the header again
    df = pd.read_csv(raw_file(settings, db, upload_id)).drop(columns=["Flow Duration"])
    df.to_csv(raw_file(settings, db, upload_id), index=False)
    assert run_queued() == ["failed"]
    failed_with(db, settings, upload_id, "required feature(s) missing: Flow Duration")


@pytest.mark.parametrize("content, text", [
    (lambda header: header, "no flows"),
    (lambda header: header + b"1,2,3\n" + b"4,5,6,7,8,9,10,11,12,13,14,15\n", "Could not read the CSV"),
])
def test_unreadable_csv(uploaded, run_queued, settings, db, content, text):
    upload_id = uploaded()
    header = flows_csv().split(b"\n", 1)[0] + b"\n"
    raw_file(settings, db, upload_id).write_bytes(content(header))
    assert run_queued() == ["failed"]
    failed_with(db, settings, upload_id, text)


def test_raw_file_gone(uploaded, run_queued, settings, db):
    upload_id = uploaded()
    raw_file(settings, db, upload_id).unlink()
    assert run_queued() == ["failed"]
    failed_with(db, settings, upload_id, "no longer available")


def test_no_active_bundle_when_the_job_runs(uploaded, run_queued, settings, db):
    upload_id = uploaded()
    db.execute(update(ModelVersion).values(status="available"))
    db.commit()
    assert run_queued() == ["failed"]
    failed_with(db, settings, upload_id, "No active model bundle")


def test_pcap_is_not_processed_yet(uploaded, run_queued, override_settings, settings, db):
    override_settings(enable_pcap=True)
    upload_id = uploaded(bytes.fromhex("d4c3b2a1") + b"\x00" * 60, filename="capture.pcap")
    assert run_queued() == ["failed"]
    failed_with(db, settings, upload_id, "PCAP processing is not available yet")


# ── deletion ────────────────────────────────────────────────

def test_deleted_before_the_job_runs(client, user, uploaded, run_queued, settings, db):
    upload_id = uploaded()
    client.delete(f"{API}/uploads/{upload_id}", headers=bearer(user))
    assert run_queued() == ["skipped"]
    assert row(db, upload_id).status == "queued" and not (settings.results_dir / upload_id).exists()


def _delete(upload_id):
    with get_sessionmaker()() as s:
        upload = s.get(Upload, uuid.UUID(upload_id))
        service.delete_upload(s, get_settings(), upload, upload.user)


def test_deleted_during_the_job(uploaded, run_queued, settings, db, monkeypatch):
    monkeypatch.setattr(processing, "BATCH_ROWS", 3)
    original = processing._set_progress
    calls = []

    def delete_after_first_batch(factory, upload_id, progress):
        calls.append(progress)
        if len(calls) == 2:
            _delete(str(upload_id))
        original(factory, upload_id, progress)

    monkeypatch.setattr(processing, "_set_progress", delete_after_first_batch)
    upload_id = uploaded(flows_csv(n_copies=5))
    assert run_queued() == ["skipped"]
    assert len(calls) == 2                                   # stopped at the next batch
    assert row(db, upload_id).deleted_at is not None and row(db, upload_id).status != "completed"
    assert not (settings.results_dir / upload_id).exists()


def test_deleted_just_before_the_results_are_recorded(uploaded, run_queued, settings, db, monkeypatch):
    original = processing._predict_csv

    def predict_then_delete(upload_id, *args):
        out = original(upload_id, *args)
        _delete(str(upload_id))
        return out

    monkeypatch.setattr(processing, "_predict_csv", predict_then_delete)
    upload_id = uploaded()
    assert run_queued() == ["skipped"]
    assert db.get(PredictionSummary, uuid.UUID(upload_id)) is None
    assert not (settings.results_dir / upload_id).exists()


# ── failures the job didn't expect (Celery's on_failure) ────

@pytest.mark.parametrize("error, text", [
    (RuntimeError("bug"), "failed unexpectedly (RuntimeError)"),
    (SoftTimeLimitExceeded(), "longer than 25 minutes"),
])
def test_unexpected_failures_still_mark_the_upload(uploaded, run_queued, settings, db, monkeypatch, error, text):
    def boom(*_):
        raise error
    monkeypatch.setattr(processing, "_predict_csv", boom)
    upload_id = uploaded()
    run_queued()
    failed_with(db, settings, upload_id, text)


def _db_down():
    return OperationalError("SELECT 1", {}, Exception("connection refused"))


def test_transient_errors_are_retried_once(uploaded, run_queued, monkeypatch):
    original, attempts = processing.process_upload, []

    def flaky(*args):
        attempts.append(1)
        if len(attempts) == 1:
            raise _db_down()
        return original(*args)

    monkeypatch.setattr(processing, "process_upload", flaky)
    uploaded()
    assert run_queued() == ["completed"] and len(attempts) == 2


def test_transient_errors_fail_after_the_retry(uploaded, run_queued, settings, db, monkeypatch):
    def down(*_):
        raise _db_down()
    monkeypatch.setattr(processing, "process_upload", down)
    upload_id = uploaded()
    run_queued()
    failed_with(db, settings, upload_id, "failed twice")


def test_queue_unavailable(client, user, active_bundle, monkeypatch, db):
    def broker_down(_):
        raise ConnectionError("redis down")
    monkeypatch.setattr(tasks, "enqueue_upload", broker_down)
    r = upload_file(client, user, flows_csv())
    assert r.status_code == 503
    [upload] = db.scalars(select(Upload)).all()
    assert upload.status == "failed" and "Could not queue" in upload.error


# ── retention ───────────────────────────────────────────────

def test_old_raw_files_are_purged(uploaded, run_queued, settings, db):
    ids = [uploaded() for _ in range(4)]
    run_queued()
    old, recent, old_failed, old_running = ids
    now = datetime.now(timezone.utc)
    for upload_id, age, status in [(old, 31, "completed"), (recent, 5, "completed"),
                                   (old_failed, 40, "failed"), (old_running, 40, "predicting")]:
        db.execute(update(Upload).where(Upload.id == uuid.UUID(upload_id))
                   .values(created_at=now - timedelta(days=age), status=status))
    db.commit()
    paths = {i: raw_file(settings, db, i) for i in ids}

    assert tasks.purge_old_uploads.apply().result == 2
    assert [paths[i].exists() for i in ids] == [False, True, False, True]
    assert row(db, old).raw_deleted_at is not None and row(db, recent).raw_deleted_at is None
    assert (settings.results_dir / old / processing.RESULTS_FILE).exists()   # results stay
    assert processing.purge_old_uploads(get_sessionmaker(), settings) == 0    # nothing twice
