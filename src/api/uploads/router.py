"""
/uploads: send a CSV (or, when enabled, a PCAP), list yours, look one up, delete one.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from src.api.auth.deps import get_current_user
from src.api.db.models import User
from src.api.db.session import get_db, get_sessionmaker
from src.api.ratelimit import UPLOADS_PER_USER, rate_limit
from src.api.runtime.model_manager import get_model_manager
from src.api.settings import get_settings
from src.api.uploads import processing, service
from src.api.uploads.schemas import UploadOut, UploadPage, UploadStatus, UploadTotals
from src.api.uploads.validation import UploadRejected
from src.api.worker import tasks

log = logging.getLogger(__name__)

router = APIRouter(prefix="/uploads", tags=["uploads"])

MULTIPART_OVERHEAD = 64 * 1024     # boundaries and part headers around the file


def _http(e: UploadRejected) -> HTTPException:
    return HTTPException(status_code=e.status, detail={"message": e.message, **e.extra} if e.extra else e.message)


def _admit(request: Request, user: User):
    """Everything that can refuse an upload before its body is read. Returns the inference engine."""
    settings = get_settings()
    rate_limit(UPLOADS_PER_USER, "upload", user.id)
    engine = get_model_manager(request).engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="No active model bundle. An admin must activate one.")
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise HTTPException(status_code=411, detail="Content-Length is required")
    if int(length) > service.upload_limit_bytes(settings) + MULTIPART_OVERHEAD:
        raise HTTPException(status_code=413, detail=f"Uploads are limited to {settings.max_upload_mb} MB")
    return engine


@router.post("", response_model=UploadOut, status_code=201)
async def create_upload(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """multipart/form-data with one file in the field `file`: a CSV exported by CICFlowMeter
    (or a PCAP / PCAPNG capture when enabled). The type is read from the file's content."""
    # No body parameters: FastAPI hasn't read the body yet, so these checks run before it arrives
    engine = await run_in_threadpool(_admit, request, user)
    async with request.form(max_files=1, max_fields=10) as form:
        file = form.get("file")
        if not isinstance(file, UploadFile):
            raise HTTPException(status_code=422, detail="Send the file as multipart/form-data in the field 'file'")
        try:
            upload = await run_in_threadpool(service.save_upload, db, get_settings(), user, file.file,
                                             file.filename, engine)
        except UploadRejected as e:
            raise _http(e)

    try:
        await run_in_threadpool(tasks.enqueue_upload, upload.id)
    except Exception:
        log.exception("Could not queue upload %s", upload.id)
        await run_in_threadpool(processing.mark_failed, get_sessionmaker(), get_settings(), upload.id,
                                "Could not queue the upload for processing; please upload it again")
        raise HTTPException(status_code=503, detail="The processing queue is unavailable; try again shortly")
    return upload


@router.get("", response_model=UploadPage)
def list_uploads(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
                 status: UploadStatus | None = None,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Your uploads, newest first."""
    items, total = service.list_uploads(db, user.id, page, size, status)
    return UploadPage(items=items, total=total, page=page, size=size)


# Before /{upload_id}: otherwise "stats" would be parsed (and rejected) as an upload id
@router.get("/stats", response_model=UploadTotals)
def upload_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Your totals: uploads per status, bytes, flows, known attacks and unknowns found."""
    return service.upload_stats(db, user.id)


@router.get("/{upload_id}", response_model=UploadOut)
def get_upload(upload_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Status, progress and error of one upload (owner or admin)."""
    try:
        return service.get_upload(db, upload_id, user)
    except UploadRejected as e:
        raise _http(e)


@router.delete("/{upload_id}", status_code=204)
def delete_upload(upload_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete the file and its results (owner or admin). The upload still counts in usage totals."""
    try:
        upload = service.get_upload(db, upload_id, user)
    except UploadRejected as e:
        raise _http(e)
    service.delete_upload(db, get_settings(), upload, user)
    return Response(status_code=204)
