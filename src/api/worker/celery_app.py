"""
Celery application (Redis broker). Upload processing tasks are added in plan §C.3.

    celery -A src.api.worker.celery_app:celery_app worker --concurrency 2 --loglevel INFO
"""

from celery import Celery

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
)
