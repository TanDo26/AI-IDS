"""
/admin endpoints. Model versions: list, rescan model_store/, activate, roll back.
"""

import redis
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.admin.schemas import ActivationOut, LoadedModel, ModelsOverview, ModelVersionOut, ProcessModel, RescanOut
from src.api.auth.deps import require_admin
from src.api.db.models import ModelVersion, User
from src.api.db.session import get_db
from src.api.runtime import model_events
from src.api.runtime.model_manager import get_model_manager
from src.api.runtime.model_registry import Activation, ModelRegistry, RegistryError
from src.api.settings import get_settings

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
    report = registry.rescan(db, admin.id)
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
