"""
The process-wide model manager (src/inference/manager.py) wired to the app's settings.
"""

from fastapi import HTTPException, Request

from src.inference.manager import ModelManager
from src.inference.store import ModelStore
from src.api.settings import Settings


def create_model_manager(settings: Settings) -> ModelManager:
    manager = ModelManager(ModelStore(settings.model_store))
    manager.ensure_current()  # load the active bundle now, if there is one
    return manager


def get_model_manager(request: Request) -> ModelManager:
    return request.app.state.models


def require_engine(request: Request):
    """FastAPI dependency: the active bundle's inference engine, or 503 when none is active."""
    engine = get_model_manager(request).engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="No active model bundle. An admin must activate one.")
    return engine
