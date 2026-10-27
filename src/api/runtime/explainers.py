"""
Explainers for the bundles that produced stored results, built once per bundle and kept per process.

Results are explained with the bundle that predicted them, which need not be the active one:
the active bundle is reused from the ModelManager, any other is loaded (and verified) from the
model store. Bundles are immutable once built, so a cached explainer never goes stale.
"""

import threading
from collections import OrderedDict

from src.inference.bundle import load_bundle
from src.inference.explain import FlowExplainer
from src.inference.manager import ModelManager


class ExplainerCache:

    def __init__(self, manager: ModelManager, size: int = 2):
        self.manager, self.size = manager, size
        self._explainers: OrderedDict[str, FlowExplainer] = OrderedDict()
        self._lock = threading.Lock()   # also serialises building: one large bundle in memory at a time

    def get(self, bundle_id: str) -> FlowExplainer:
        """Raises BundleError when the bundle can no longer be loaded (removed or broken)."""
        with self._lock:
            if bundle_id in self._explainers:
                self._explainers.move_to_end(bundle_id)
                return self._explainers[bundle_id]
            current = self.manager.current()
            bundle = current if current is not None and current.bundle_id == bundle_id \
                else load_bundle(self.manager.store.root / bundle_id)
            explainer = FlowExplainer(bundle)
            self._explainers[bundle_id] = explainer
            while len(self._explainers) > self.size:
                self._explainers.popitem(last=False)
            return explainer
