"""
The process-wide model manager (src/inference/manager.py), backed by the database registry,
and the runtime that keeps it current.
"""

import logging
import threading

from fastapi import HTTPException, Request

from src.api.db.session import get_sessionmaker
from src.api.runtime import model_events
from src.api.runtime.model_registry import ModelRegistry
from src.api.settings import Settings
from src.inference.manager import ModelManager

log = logging.getLogger(__name__)


def create_model_manager(settings: Settings, load: bool = True) -> ModelManager:
    """A manager following the database's active version; load=True loads that bundle now."""
    manager = ModelManager(ModelRegistry(settings.model_store, get_sessionmaker()))
    if load:
        try:
            manager.ensure_current()
        except Exception:
            log.exception("Could not read the active model version; the next check retries")
    return manager


class ModelRuntime:
    """Keeps one process's model current, and visible on the admin page.

    - a database check every model_poll_seconds (the fallback);
    - with listen=True (API processes), Redis model events for an immediate switch;
    - after every check, a report of what this process has loaded (key with a TTL).
    """

    def __init__(self, manager: ModelManager, settings: Settings, kind: str, listen: bool):
        self.manager, self.kind = manager, kind
        self.interval = settings.model_poll_seconds
        self.redis_url = settings.redis_url
        self.events = settings.model_events_enabled
        self.report_ttl = max(3 * self.interval, 60)
        self._stop = threading.Event()
        self._poller = threading.Thread(target=self._poll, name="model-poller", daemon=True)
        self._listener = model_events.EventListener(self.redis_url, self.sync) if listen and self.events else None

    def sync(self):
        """Switch to the active version if it changed, then report what is loaded."""
        try:
            self.manager.ensure_current()
        except Exception:
            log.exception("Checking the active model version failed; keeping %s", self.manager.status()["loaded"])
        if self.events:
            model_events.report_loaded(self.redis_url, self.kind, self.manager.status(), self.report_ttl)

    def _poll(self):
        self.sync()
        while not self._stop.wait(self.interval):
            self.sync()

    def start(self):
        self._poller.start()
        if self._listener:
            self._listener.start()

    def stop(self):
        self._stop.set()
        if self._listener:
            self._listener.stop()
        self._poller.join()
        if self.events:
            model_events.clear_report(self.redis_url)


def get_model_manager(request: Request) -> ModelManager:
    return request.app.state.models


def require_engine(request: Request):
    """FastAPI dependency: the active bundle's inference engine, or 503 when none is active."""
    engine = get_model_manager(request).engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="No active model bundle. An admin must activate one.")
    return engine
