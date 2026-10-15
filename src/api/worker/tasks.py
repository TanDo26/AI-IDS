"""
Celery tasks. process_upload / purge_old_uploads come with plan §C.3.
"""

from celery.signals import worker_process_init, worker_process_shutdown

from src.api.runtime.model_manager import ModelRuntime, create_model_manager
from src.api.settings import get_settings
from src.api.worker.celery_app import celery_app
from src.inference.manager import ModelManager

_models: ModelManager | None = None
_runtime: ModelRuntime | None = None


def _manager() -> ModelManager:
    global _models
    if _models is None:
        _models = create_model_manager(get_settings(), load=False)
    return _models


def worker_models() -> ModelManager:
    """This worker process's model manager, switched to the active version at the start of each job."""
    manager = _manager()
    manager.ensure_current()
    return manager


@worker_process_init.connect
def _start_model_runtime(**_):
    """Prefork children: load the active bundle before the first job, re-check it in the background
    and report it for the admin page. Loading happens in the runtime's thread, because this signal
    must return within worker_proc_alive_timeout (4 s) and a large bundle loads slower.
    (Not sent with --pool solo; jobs still switch when they start.)"""
    global _runtime
    _runtime = ModelRuntime(_manager(), get_settings(), kind="worker", listen=False)
    _runtime.start()


@worker_process_shutdown.connect
def _stop_model_runtime(**_):
    if _runtime is not None:
        _runtime.stop()


@celery_app.task(name="ids.ping")
def ping() -> dict:
    """Round trip through the broker; reports the bundle this worker has loaded."""
    return {"pong": True, "model": worker_models().status()["loaded"]}
