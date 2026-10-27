"""
/admin endpoints:
- model versions: list, rescan model_store/, activate, roll back;
- users: list, (de)activate, promote/demote;
- usage per user and per day;
- all uploads;
- the audit log;
- server status.
"""

from datetime import date

import redis
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.admin import service, status
from src.api.admin.schemas import (
    ActivationOut, AdminUploadOut, AdminUploadPage, AuditOut, AuditPage, DailyUsageOut, LoadedModel,
    ModelsOverview, ModelVersionOut, ProcessModel, RescanOut, Role, ServerStatus, UsageOut, UserAdminOut, UserPage,
    UserUpdate,
)
from src.api.auth.deps import require_admin
from src.api.db.models import ModelVersion, User
from src.api.db.session import get_db
from src.api.runtime import model_events
from src.api.runtime.model_manager import get_model_manager
from src.api.runtime.model_registry import Activation, ModelRegistry, RegistryError
from src.api.settings import get_settings
from src.api.uploads.schemas import UploadOut, UploadStatus

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def get_registry(request: Request) -> ModelRegistry:
    return get_model_manager(request).store


def _versions(db: Session) -> list[ModelVersionOut]:
    rows = db.scalars(select(ModelVersion).order_by(ModelVersion.registered_at.desc(), ModelVersion.id.desc()))
    return [ModelVersionOut.from_row(row) for row in rows]


@router.get("/models", response_model=ModelsOverview)
def list_models(request: Request, db: Session = Depends(get_db)):
    versions = _versions(db)
    active = next((v.bundle_id for v in versions if v.status == "active"), None)

    settings, processes = get_settings(), None
    if settings.model_events_enabled:
        try:
            processes = [ProcessModel(**{k: r.get(k) for k in ProcessModel.model_fields if k != "lagging"},
                                      lagging=r.get("loaded") != active)
                         for r in model_events.loaded_by_process(settings.redis_url)]
        except redis.RedisError:
            processes = None
    return ModelsOverview(active=active, versions=versions,
                          this_process=LoadedModel(**get_model_manager(request).status()), processes=processes)


@router.post("/models/rescan", response_model=RescanOut)
def rescan(registry: ModelRegistry = Depends(get_registry), admin: User = Depends(require_admin),
           db: Session = Depends(get_db)):
    try:
        report = registry.rescan(db, admin.id)
    except RegistryError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    return RescanOut(**report.__dict__, versions=_versions(db))


def _switched(request: Request, background: BackgroundTasks, activation: Activation) -> ActivationOut:
    notified = False
    if activation.changed:
        settings = get_settings()
        if settings.model_events_enabled:
            notified = model_events.publish(settings.redis_url, {"type": "activated",
                                                                 "bundle_id": activation.version.bundle_id,
                                                                 "version_id": activation.version.id})
        background.add_task(request.app.state.model_runtime.sync)  # this process switches right away
    return ActivationOut(version=ModelVersionOut.from_row(activation.version), previous=activation.previous,
                         changed=activation.changed, notified=notified)


@router.post("/models/{version_id}/activate", response_model=ActivationOut)
def activate(version_id: int, request: Request, background: BackgroundTasks,
             registry: ModelRegistry = Depends(get_registry), admin: User = Depends(require_admin),
             db: Session = Depends(get_db)):
    try:
        activation = registry.activate(db, version_id, admin.id)
    except RegistryError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    return _switched(request, background, activation)


@router.post("/models/rollback", response_model=ActivationOut)
def rollback(request: Request, background: BackgroundTasks,
             registry: ModelRegistry = Depends(get_registry), admin: User = Depends(require_admin),
             db: Session = Depends(get_db)):
    try:
        activation = registry.rollback(db, admin.id)
    except RegistryError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    return _switched(request, background, activation)


def _raise(e: service.AdminError):
    raise HTTPException(status_code=e.status, detail=e.message)


# ── users ───────────────────────────────────────────────────

@router.get("/users", response_model=UserPage)
def list_users(q: str | None = Query(None, max_length=320, description="Part of an email or username"),
               role: Role | None = None, active: bool | None = None,
               page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    items, total = service.list_users(db, q, role, active, page, size)
    return UserPage(items=items, total=total, page=page, size=size)


@router.patch("/users/{user_id}", response_model=UserAdminOut)
def update_user(user_id: int, body: UserUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Deactivate/reactivate (deactivation ends the user's sessions) and promote/demote, each audited.
    Nobody can change their own role or status, and the last active admin can't be removed."""
    try:
        return service.update_user(db, admin, user_id, body.is_active, body.role)
    except service.AdminError as e:
        _raise(e)


# ── usage ───────────────────────────────────────────────────

@router.get("/usage", response_model=UsageOut)
def usage(from_: date | None = Query(None, alias="from", description="First UTC day (default: all time)"),
          to: date | None = Query(None, description="Last UTC day, included"), db: Session = Depends(get_db)):
    """Per-user totals for uploads created in the period, plus storage held right now."""
    try:
        rows = service.usage(db, get_settings(), from_, to)
    except service.AdminError as e:
        _raise(e)
    totals = {k: sum(r[k] for r in rows) for k in ("uploads", "failed_uploads", "deleted_uploads", "bytes", "flows",
                                                   "processing_ms", "storage_bytes")}
    return UsageOut(from_=from_, to=to, users=rows, totals=totals)


@router.get("/usage/{user_id}/daily", response_model=DailyUsageOut)
def daily_usage(user_id: int, from_: date | None = Query(None, alias="from"), to: date | None = None,
                db: Session = Depends(get_db)):
    """One user's uploads per UTC day (default: the last 30 days, at most 366)."""
    try:
        start, end, days = service.daily_usage(db, user_id, from_, to)
    except service.AdminError as e:
        _raise(e)
    return DailyUsageOut(user_id=user_id, from_=start, to=end, days=days)


# ── uploads and audit ───────────────────────────────────────

@router.get("/uploads", response_model=AdminUploadPage)
def all_uploads(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), user_id: int | None = None,
                status: UploadStatus | None = None,
                deleted: bool = Query(False, description="Include uploads their owner deleted"),
                db: Session = Depends(get_db)):
    """Every user's uploads, newest first."""
    rows, total = service.list_uploads(db, page, size, user_id, status, deleted)
    items = [AdminUploadOut(**UploadOut.model_validate(upload).model_dump(), owner_email=email,
                            owner_username=username, deleted_at=upload.deleted_at)
             for upload, email, username in rows]
    return AdminUploadPage(items=items, total=total, page=page, size=size)


@router.get("/audit", response_model=AuditPage)
def audit(page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
          action: str | None = Query(None, max_length=64, description="e.g. model.activate, or user. for a family"),
          actor_id: int | None = None, target_type: str | None = Query(None, max_length=32),
          target_id: str | None = Query(None, max_length=64), db: Session = Depends(get_db)):
    """Audit log, newest first."""
    rows, total = service.list_audit(db, page, size, action, actor_id, target_type, target_id)
    items = [AuditOut(id=log.id, actor_id=log.actor_id, actor_email=email, action=log.action,
                      target_type=log.target_type, target_id=log.target_id, details=log.details or {},
                      created_at=log.created_at)
             for log, email in rows]
    return AuditPage(items=items, total=total, page=page, size=size)


# ── server ──────────────────────────────────────────────────

@router.get("/server", response_model=ServerStatus)
def server(request: Request, db: Session = Depends(get_db)):
    """Host, database, Redis, queue, uploads and model state of the API process that answers,
    with warnings. Takes about a second (CPU sampling and a worker ping)."""
    return status.server_status(db, get_settings(), get_model_manager(request), request.app.state.started_at,
                                request.app.version)
