"""
Upload storage and lookups.

Files are stored as <data_dir>/uploads/<user_id>/<upload_id>.<type>, under a name the server
makes up; the client's filename is only displayed. `stored_path` is relative to the data
directory, so the same rows work in the container (/data) and on the host.
"""

import hashlib
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.db.models import AuditLog, PredictionSummary, Upload, User
from src.api.settings import Settings
from src.api.uploads.validation import HEAD_BYTES, UploadRejected, detect_file_type
from src.inference.engine import InferenceEngine

log = logging.getLogger(__name__)

CHUNK_BYTES = 1 << 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


def upload_limit_bytes(settings: Settings) -> int:
    return settings.max_upload_mb * 1_000_000     # decimal MB, as Caddy's "100MB"


def display_name(filename: str | None) -> str:
    """The client's filename without any directory part or control characters, for display only."""
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name[:255] or "upload"


def raw_path(settings: Settings, upload: Upload) -> Path:
    return settings.data_dir / upload.stored_path


def results_dir(settings: Settings, upload_id) -> Path:
    return settings.results_dir / str(upload_id)


def _store(src, dest: Path, head: bytes, limit: int) -> tuple[int, str]:
    """Copy head + the rest of src to dest, hashing as it goes. Returns (size, sha256)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".part")
    digest, size = hashlib.sha256(), 0
    try:
        with open(partial, "wb") as out:
            chunk = head
            while chunk:
                size += len(chunk)
                if size > limit:
                    raise UploadRejected(413, f"Uploads are limited to {limit // 1_000_000} MB")
                digest.update(chunk)
                out.write(chunk)
                chunk = src.read(CHUNK_BYTES)
        os.replace(partial, dest)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return size, digest.hexdigest()


def save_upload(db: Session, settings: Settings, user: User, src, filename: str | None,
                engine: InferenceEngine) -> Upload:
    """Check, store and record one uploaded file (a binary file object), queued for processing."""
    head = src.read(HEAD_BYTES)
    file_type, columns = detect_file_type(head, complete=len(head) < HEAD_BYTES)
    if file_type != "csv" and not settings.enable_pcap:
        raise UploadRejected(415, "PCAP uploads are not enabled yet (the flow extractor is still being "
                                  "validated); upload a CSV exported by CICFlowMeter instead")
    if columns is not None:
        missing = engine.missing_features(columns)
        if missing:  # caught now rather than after queueing; the worker checks again
            raise UploadRejected(422, f"{len(missing)} required feature(s) missing: {', '.join(missing)}",
                                 missing=missing)

    upload_id = uuid.uuid4()
    relative = PurePosixPath("uploads", str(user.id), f"{upload_id}.{file_type}")
    dest = settings.data_dir / relative
    size, sha256 = _store(src, dest, head, upload_limit_bytes(settings))

    upload = Upload(id=upload_id, user_id=user.id, original_filename=display_name(filename),
                    stored_path=str(relative), file_type=file_type, size_bytes=size, sha256=sha256,
                    created_at=_now())  # microseconds, so "newest first" is exact
    db.add(upload)
    try:
        db.commit()
    except Exception:
        db.rollback()
        dest.unlink(missing_ok=True)
        raise
    return upload


def list_uploads(db: Session, user_id: int, page: int, size: int, status: str | None = None
                 ) -> tuple[list[Upload], int]:
    query = select(Upload).where(Upload.user_id == user_id, Upload.deleted_at.is_(None))
    if status is not None:
        query = query.where(Upload.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(Upload.created_at.desc(), Upload.id)
                       .offset((page - 1) * size).limit(size)).all()
    return list(items), total


def upload_stats(db: Session, user_id: int) -> dict:
    """One user's totals over the uploads they still have (deleted ones are gone from their view)."""
    live = (Upload.user_id == user_id, Upload.deleted_at.is_(None))
    by_status = dict(db.execute(select(Upload.status, func.count()).where(*live).group_by(Upload.status)).all())
    size, flows, last = db.execute(select(func.coalesce(func.sum(Upload.size_bytes), 0),
                                          func.coalesce(func.sum(Upload.n_flows), 0),
                                          func.max(Upload.created_at)).where(*live)).one()
    known, unknown = db.execute(select(func.coalesce(func.sum(PredictionSummary.n_known_attack), 0),
                                       func.coalesce(func.sum(PredictionSummary.n_unknown), 0))
                                .join(Upload, PredictionSummary.upload_id == Upload.id).where(*live)).one()
    return {"uploads": sum(by_status.values()), "by_status": by_status, "bytes": int(size), "flows": int(flows),
            "known_attacks": int(known), "unknown": int(unknown), "last_upload_at": last}


def get_upload(db: Session, upload_id: uuid.UUID, user: User) -> Upload:
    """The upload if this user may see it (owner or admin). Otherwise 404, never 403,
    so nobody can probe which upload ids exist."""
    upload = db.get(Upload, upload_id)
    if upload is None or upload.deleted_at is not None or (upload.user_id != user.id and user.role != "admin"):
        raise UploadRejected(404, "Upload not found")
    return upload


def delete_upload(db: Session, settings: Settings, upload: Upload, actor: User) -> None:
    """Delete the raw file, the results and the summary. The row stays (marked deleted) for usage totals."""
    now = _now()
    if upload.summary is not None:
        db.delete(upload.summary)
    upload.deleted_at = now
    upload.raw_deleted_at = upload.raw_deleted_at or now
    if actor.id != upload.user_id:
        db.add(AuditLog(actor_id=actor.id, action="upload.delete", target_type="upload", target_id=str(upload.id),
                        details={"owner_id": upload.user_id, "filename": upload.original_filename}))
    db.commit()

    # Files go after the commit: a leftover file is harmless, a row pointing at nothing is not
    try:
        raw_path(settings, upload).unlink(missing_ok=True)
    except OSError as e:
        log.warning("Could not delete %s: %s", upload.stored_path, e)
    shutil.rmtree(results_dir(settings, upload.id), ignore_errors=True)
