"""
Celery tasks. process_upload / purge_old_uploads come with plan §C.3.
"""

from src.api.settings import get_settings
from src.api.worker.celery_app import celery_app
from src.inference.manager import ModelManager
from src.inference.store import ModelStore

_models: ModelManager | None = None


def worker_models() -> ModelManager:
    """This worker process's model manager, switched to the active bundle at the start of each job."""
    global _models
    if _models is None:
        _models = ModelManager(ModelStore(get_settings().model_store))
    _models.ensure_current()
    return _models


@celery_app.task(name="ids.ping")
def ping() -> dict:
    """Round trip through the broker; reports the bundle this worker has loaded."""
    return {"pong": True, "model": worker_models().status()["loaded"]}
