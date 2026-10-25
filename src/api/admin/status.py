"""
GET /admin/server: what an admin checks first when something seems off, plus plain-language warnings.

Redis is checked once; when it's down the queue and worker checks are skipped rather than each
timing out, so the page answers in about a second either way.
"""

import time
from datetime import datetime, timedelta, timezone

import redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api import health
from src.api.db.models import Upload
from src.api.runtime import model_events
from src.api.runtime.system_stats import system_stats
from src.api.settings import Settings
from src.api.worker.celery_app import celery_app
from src.inference.manager import ModelManager

CELERY_QUEUE = "celery"            # kombu's Redis list for the default queue
UNACKED = "unacked"                # kombu's hash of delivered, unacknowledged tasks (acks_late: running or reserved)
WORKER_PING_TIMEOUT_S = 0.5
STUCK_AFTER = timedelta(minutes=35)   # past the 30-min hard limit, on_failure should have marked the upload
RAM_WARNING_PERCENT = 90              # large uploads and explanations need headroom; workers get killed without it


def queue_status(redis_url: str) -> dict:
    client = redis.Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
    queued, unacknowledged = client.llen(CELERY_QUEUE), client.hlen(UNACKED)
    replies = celery_app.control.ping(timeout=WORKER_PING_TIMEOUT_S)     # [{"celery@host": {"ok": "pong"}}, ...]
    return {"ok": True, "queued": queued, "unacknowledged": unacknowledged,
            "workers": sorted(name for reply in replies for name in reply)}


def upload_stats(db: Session, now: datetime) -> dict:
    live = Upload.deleted_at.is_(None)
    by_status = dict(db.execute(select(Upload.status, func.count()).where(live).group_by(Upload.status)).all())
    failed_24h = db.scalar(select(func.count()).where(live, Upload.status == "failed",
                                                      Upload.finished_at >= now - timedelta(hours=24)))
    stuck = db.scalar(select(func.count()).where(live, Upload.status.in_(("converting", "predicting")),
                                                 Upload.started_at < now - STUCK_AFTER))
    return {"by_status": by_status, "failed_last_24h": failed_24h, "stuck": stuck}


def server_status(db: Session, settings: Settings, manager: ModelManager, started_at: float, version: str) -> dict:
    now = datetime.now(timezone.utc)
    warnings = []

    system = system_stats(settings.data_dir)
    system["disk_warning"] = system["disk_percent"] >= settings.disk_warning_percent
    if system["disk_warning"]:
        warnings.append(f"The data volume is {system['disk_percent']:.0f}% full "
                        f"(warning from {settings.disk_warning_percent}%)")
    if system["ram_percent"] >= RAM_WARNING_PERCENT:
        warnings.append(f"Memory is {system['ram_percent']:.0f}% used: processing large uploads may slow down or fail")

    database = health._check_database()
    if not database["ok"]:
        warnings.append("The database is unreachable")
    redis_check = health._check_redis(settings.redis_url)
    queue = {"ok": False, "error": "Redis is unreachable"}
    if not redis_check["ok"]:
        warnings.append("Redis is unreachable: uploads can't be queued, and model switches wait for the next poll")
    else:
        try:
            queue = queue_status(settings.redis_url)
        except Exception as e:
            queue = {"ok": False, "error": type(e).__name__}
        if queue["ok"] and not queue["workers"]:
            warnings.append("No Celery worker answered: uploads will stay queued")

    uploads = None
    if database["ok"]:
        uploads = upload_stats(db, now)
        if uploads["stuck"]:
            warnings.append(f"{uploads['stuck']} upload(s) have been processing for over "
                            f"{int(STUCK_AFTER.total_seconds() // 60)} minutes")

    model = {**manager.status(), "lagging_processes": None}
    if model["active_in_store"] is None:
        warnings.append("No model is active: uploads and predictions are refused until an admin activates one")
    elif model["loaded"] != model["active_in_store"]:
        warnings.append(f"This API process serves {model['loaded']}, not the active {model['active_in_store']}")
    if model["last_error"]:
        warnings.append(f"The last model load failed: {model['last_error']}")
    if settings.model_events_enabled and redis_check["ok"]:
        try:
            reports = model_events.loaded_by_process(settings.redis_url)
            model["lagging_processes"] = sum(r.get("loaded") != model["active_in_store"] for r in reports)
        except redis.RedisError:
            pass
        if model["lagging_processes"]:
            warnings.append(f"{model['lagging_processes']} process(es) still serve an older model")

    return {
        "checked_at": now,
        "api": {"version": version, "process": model_events.process_id(),
                "started_at": datetime.fromtimestamp(started_at, timezone.utc),
                "uptime_s": int(time.time() - started_at)},
        "system": system, "database": database, "redis": redis_check, "queue": queue,
        "uploads": uploads, "model": model, "warnings": warnings,
    }
