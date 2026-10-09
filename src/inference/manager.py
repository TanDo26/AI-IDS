"""
Model manager: the active bundle for one process, swapped when the store's active bundle changes.
"""

import logging
import threading
from datetime import datetime

from .bundle import load_bundle, BundleError
from .engine import InferenceEngine

log = logging.getLogger(__name__)


class ModelManager:

    def __init__(self, store):
        self.store = store
        self._lock = threading.Lock()
        self._bundle = None
        self._engine = None
        self._loaded_at = None
        self._last_error = None
        self._poller = None

    def current(self):
        return self._bundle

    def engine(self) -> InferenceEngine | None:
        return self._engine

    def ensure_current(self):
        """Load the store's active bundle if it isn't the one loaded. Returns the current bundle."""
        active = self.store.active_id()
        if active == (self._bundle.bundle_id if self._bundle else None):
            return self._bundle

        with self._lock:
            loaded = self._bundle.bundle_id if self._bundle else None
            if active == loaded:          # another thread swapped while we waited
                return self._bundle
            if active is None:
                self._bundle, self._engine, self._loaded_at = None, None, None
                return None
            try:
                bundle = load_bundle(self.store.root / active)
            except BundleError as e:
                self._last_error = f"{datetime.now().isoformat(timespec='seconds')} {e}"
                log.error("Keeping %s: could not load %s: %s", loaded, active, e)
                return self._bundle
            self._bundle, self._engine = bundle, InferenceEngine(bundle)
            self._loaded_at = datetime.now().isoformat(timespec="seconds")
            self._last_error = None
            log.info("Switched model bundle %s -> %s", loaded, active)
            return bundle

    def start_polling(self, interval_s: float = 30.0):
        """Check the store every interval_s seconds in a daemon thread."""
        stop = threading.Event()

        def loop():
            while not stop.wait(interval_s):
                try:
                    self.ensure_current()
                except Exception:
                    log.exception("Model poll failed")

        self._poller = (threading.Thread(target=loop, name="model-poller", daemon=True), stop)
        self._poller[0].start()

    def stop_polling(self):
        if self._poller:
            self._poller[1].set()
            self._poller[0].join()
            self._poller = None

    def status(self) -> dict:
        return {
            "loaded": self._bundle.bundle_id if self._bundle else None,
            "loaded_at": self._loaded_at,
            "active_in_store": self.store.active_id(),
            "last_error": self._last_error,
        }
