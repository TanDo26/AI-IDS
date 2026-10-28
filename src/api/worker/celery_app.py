"""
Celery application (Redis broker): upload processing, plus a daily retention job run by beat.

    celery -A src.api.worker.celery_app:celery_app worker --concurrency 2 --loglevel INFO
    celery -A src.api.worker.celery_app:celery_app beat --loglevel INFO
"""

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging, task_postrun, task_prerun

from src.api import logs
from src.api.settings import get_settings

settings = get_settings()


@setup_logging.connect
def _configure_logging(loglevel=None, **_):
    """Replaces Celery's own logging setup: same format as the API (IDS_LOG_FORMAT)."""
    logs.configure_logging(settings.log_format, loglevel or settings.log_level)


@task_prerun.connect
def _task_started(task_id=None, task=None, **_):
    logs.task.set((task_id, task.name if task else None))


@task_postrun.connect
def _task_finished(**_):
    logs.task.set(None)

celery_app = Celery("ids", broker=settings.redis_url, backend=settings.redis_url,
                    include=["src.api.worker.tasks"])
celery_app.conf.update(
    task_acks_late=True,                    # a crashed worker's job is redelivered
    worker_prefetch_multiplier=1,           # long jobs: don't hoard tasks
    worker_max_tasks_per_child=50,          # recycle processes to bound memory
    task_soft_time_limit=25 * 60,
    task_time_limit=30 * 60,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    beat_schedule={
        # Raw uploads older than IDS_RETENTION_DAYS; results and usage rows stay
        "purge-old-uploads": {"task": "ids.purge_old_uploads", "schedule": crontab(hour=3, minute=30)},
    },
)
