"""
The Redis side of model switching:
- `ids:model-events` (pub/sub): "the active version changed", so API processes re-check at once
  instead of at their next poll. The database stays the source of truth: a lost message only
  delays a switch until the next poll.
- `ids:model-loaded:<host>:<pid>` (keys with a TTL): what each process has loaded, so the admin
  page can show processes that lag behind. A process that stops reporting drops out.
"""

import json
import logging
import os
import socket
import threading
from datetime import datetime, timezone
from functools import lru_cache

import redis

log = logging.getLogger(__name__)

CHANNEL = "ids:model-events"
LOADED_PREFIX = "ids:model-loaded:"


def process_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


@lru_cache
def _client(url: str) -> redis.Redis:
    return redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True)


def publish(url: str, event: dict) -> bool:
    """Tell every process to re-check the active version. False if Redis is unreachable."""
    try:
        _client(url).publish(CHANNEL, json.dumps(event))
        return True
    except redis.RedisError as e:
        log.warning("Could not publish model event (%s); processes switch at their next poll", type(e).__name__)
        return False


def report_loaded(url: str, kind: str, status: dict, ttl_s: float) -> None:
    payload = {"process": process_id(), "kind": kind, **status,
               "reported_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        _client(url).set(LOADED_PREFIX + process_id(), json.dumps(payload), ex=int(ttl_s))
    except redis.RedisError as e:
        log.debug("Could not report the loaded model (%s)", type(e).__name__)


def clear_report(url: str) -> None:
    try:
        _client(url).delete(LOADED_PREFIX + process_id())
    except redis.RedisError:
        pass


def loaded_by_process(url: str) -> list[dict]:
    """Every live process's report. Raises redis.RedisError when Redis is unreachable."""
    client = _client(url)
    keys = sorted(client.scan_iter(match=LOADED_PREFIX + "*", count=100))
    values = client.mget(keys) if keys else []
    return [json.loads(v) for v in values if v]   # a key can expire between SCAN and MGET


class EventListener:
    """Calls on_change() for every model event, and after each (re)subscribe to catch up."""

    def __init__(self, url: str, on_change, retry_s: float = 5.0):
        self.url, self.on_change, self.retry_s = url, on_change, retry_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="model-events", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self, timeout_s: float = 3.0):
        self._stop.set()
        self._thread.join(timeout_s)

    def _run(self):
        while not self._stop.is_set():
            pubsub = None
            try:
                client = redis.Redis.from_url(self.url, socket_connect_timeout=2, health_check_interval=30,
                                              decode_responses=True)
                pubsub = client.pubsub(ignore_subscribe_messages=True)
                pubsub.subscribe(CHANNEL)
                self.on_change()             # events sent while we were disconnected are lost
                while not self._stop.is_set():
                    message = pubsub.get_message(timeout=1.0)
                    if message is not None:
                        log.info("Model event: %s", message["data"])
                        self.on_change()
            except redis.RedisError as e:
                log.warning("Model events unavailable (%s); retrying in %.0f s, polling meanwhile",
                            type(e).__name__, self.retry_s)
                self._stop.wait(self.retry_s)
            except Exception:
                log.exception("Model event listener failed; retrying in %.0f s", self.retry_s)
                self._stop.wait(self.retry_s)
            finally:
                if pubsub is not None:
                    pubsub.close()
