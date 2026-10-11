"""
Liveness and readiness probes.
"""

import redis
from fastapi import APIRouter, Request, Response
from sqlalchemy import text

from src.api.db.session import get_engine

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz():
    """Liveness: the process is up (used by the container healthcheck)."""
    return {"status": "ok"}


def _check_database() -> dict:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


def _check_redis(url: str) -> dict:
    try:
        redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1).ping()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


@router.get("/readyz")
def readyz(request: Request, response: Response):
    """Readiness: database, Redis and an active model bundle are all available."""
    status = request.app.state.models.status()
    checks = {
        "database": _check_database(),
        "redis": _check_redis(request.app.state.settings.redis_url),
        "model": {"ok": status["loaded"] is not None, **status},
    }
    ready = all(c["ok"] for c in checks.values())
    response.status_code = 200 if ready else 503
    return {"ready": ready, "checks": checks}
