"""
Celery tasks: process_upload (one per upload), purge_old_uploads (daily, from beat), ping.
"""

import logging
import uuid

import redis
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded, WorkerLostError
from celery.signals import worker_process_init, worker_process_shutdown
from sqlalchemy.exc import OperationalError

from src.api.db.session import get_engine, get_sessionmaker
from src.api.runtime.model_manager import ModelRuntime, create_model_manager
from src.api.settings import get_settings
from src.api.uploads import processing
from src.api.worker.celery_app import celery_app
from src.inference.manager import ModelManager

log = logging.getLogger(__name__)

_models: ModelManager | None = None
_runtime: ModelRuntime | None = None

# Worth one more try: the database or Redis was briefly unreachable
TRANSIENT_ERRORS = (OperationalError, redis.ConnectionError, redis.TimeoutError)
RETRY_DELAY_S = 30


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
    get_engine().dispose(close=False)  # never share the parent's pooled DB connections after fork
    _runtime = ModelRuntime(_manager(), get_settings(), kind="worker", listen=False)
    _runtime.start()


@worker_process_shutdown.connect
def _stop_model_runtime(**_):
    if _runtime is not None:
        _runtime.stop()


def failure_message(exc: BaseException) -> str:
    if isinstance(exc, (SoftTimeLimitExceeded, TimeLimitExceeded)):
        return f"Processing took longer than {celery_app.conf.task_soft_time_limit // 60} minutes"
    if isinstance(exc, WorkerLostError):
        return "The worker stopped while processing this upload (out of memory?)"
    if isinstance(exc, TRANSIENT_ERRORS):
        return "Processing failed twice: the database or Redis was unavailable"
    return f"Processing failed unexpectedly ({type(exc).__name__})"


class UploadTask(Task):

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Every failure that escaped the job (time limits, a killed worker, bugs, transient errors
        after the retry) still leaves the upload `failed` with a message, never stuck in `predicting`."""
        upload_id = args[0] if args else kwargs.get("upload_id")
        try:
            processing.mark_failed(get_sessionmaker(), get_settings(), uuid.UUID(upload_id), failure_message(exc))
        except Exception:
            log.exception("Could not mark upload %s as failed", upload_id)


@celery_app.task(bind=True, base=UploadTask, name="ids.process_upload", max_retries=1)
def process_upload(self, upload_id: str) -> str:
    try:
        return processing.process_upload(uuid.UUID(upload_id), worker_models(), get_settings(), get_sessionmaker())
    except TRANSIENT_ERRORS as e:
        log.warning("Upload %s: %s, retrying once in %d s", upload_id, type(e).__name__, RETRY_DELAY_S)
        raise self.retry(exc=e, countdown=RETRY_DELAY_S)


def enqueue_upload(upload_id: uuid.UUID) -> None:
    """Queue an upload for processing; raises if the broker can't be reached."""
    process_upload.apply_async(args=[str(upload_id)], retry=True,
                               retry_policy={"max_retries": 2, "interval_start": 0, "interval_step": 0.5})


@celery_app.task(name="ids.purge_old_uploads")
def purge_old_uploads() -> int:
    return processing.purge_old_uploads(get_sessionmaker(), get_settings())


@celery_app.task(name="ids.ping")
def ping() -> dict:
    """Round trip through the broker; reports the bundle this worker has loaded."""
    return {"pong": True, "model": worker_models().status()["loaded"]}
