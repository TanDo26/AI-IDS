"""
Rate limits, shared across API processes through Redis.

The `limits` library is used directly (not slowapi's decorators) because the per-account
login limit is keyed by the email in the request body. If Redis is unreachable, limits
fall back to per-process memory instead of failing requests.
"""

import logging
import time
from functools import lru_cache

from fastapi import HTTPException
from limits import parse
from limits.storage import MemoryStorage, storage_from_string
from limits.strategies import FixedWindowRateLimiter

from src.api.settings import get_settings

log = logging.getLogger(__name__)

LOGIN_PER_IP = "5/minute"
LOGIN_PER_ACCOUNT = "20/hour"
SIGNUP_PER_IP = "3/hour"
UPLOADS_PER_USER = "10/minute"


class RateLimiter:

    def __init__(self, redis_url: str | None):
        self._redis = None
        if redis_url:
            storage = storage_from_string(redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
            self._redis = FixedWindowRateLimiter(storage)
        self._memory = FixedWindowRateLimiter(MemoryStorage())

    def check(self, limit: str, *keys) -> None:
        """Count one hit; raise 429 (with Retry-After) once the limit is exceeded."""
        item = parse(limit)
        limiter = self._memory
        if self._redis is not None:
            try:
                if self._redis.hit(item, *keys):
                    return
                limiter = self._redis
            except Exception as e:  # Redis down: per-process limits are better than none
                log.warning("Rate-limit storage unavailable (%s); using in-memory limits", type(e).__name__)
                if self._memory.hit(item, *keys):
                    return
        elif self._memory.hit(item, *keys):
            return
        reset_at, _ = limiter.get_window_stats(item, *keys)
        retry_after = max(1, int(reset_at - time.time()))
        raise HTTPException(status_code=429, detail="Too many requests, try again later.",
                            headers={"Retry-After": str(retry_after)})


@lru_cache
def get_rate_limiter() -> RateLimiter:
    return RateLimiter(get_settings().redis_url)


def rate_limit(limit: str, *keys) -> None:
    if get_settings().rate_limits_enabled:
        get_rate_limiter().check(limit, *keys)
