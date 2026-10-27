"""
Celery application (Redis broker): upload processing, plus a daily retention job run by beat.

    celery -A src.api.worker.celery_app:celery_app worker --concurrency 2 --loglevel INFO
    celery -A src.api.worker.celery_app:celery_app beat --loglevel INFO
"""

from celery import Celery
from celery.schedules import crontab

from src.api.settings import get_settings

settings = get_settings()

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
