"""
Model store: the bundles in model_store/ and which one is active.
"""

import os
import json
import getpass
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .bundle import load_bundle, BundleError, MANIFEST

REGISTRY_FILE = "registry.json"


@dataclass
class BundleInfo:
    bundle_id: str
    path: Path
    status: str                      # "active" | "available" | "invalid"
    error: str | None = None
    manifest: dict = field(default_factory=dict)


class ModelStore:

    def __init__(self, root):
        self.root = Path(root)

    def state(self) -> dict:
        path = self.root / REGISTRY_FILE
        if not path.exists():
            return {"active": None, "history": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def active_id(self) -> str | None:
        return self.state()["active"]

    def _write_state(self, state: dict):
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / (REGISTRY_FILE + ".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, self.root / REGISTRY_FILE)  # atomic: readers never see a half-written file

    def bundle_ids(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if (p / MANIFEST).exists())

    def scan(self) -> list[BundleInfo]:
        """Verify every bundle (format, hashes, versions, self-test)."""
        active = self.active_id()
        infos = []
        for bundle_id in self.bundle_ids():
            path = self.root / bundle_id
            try:
                manifest = load_bundle(path).manifest
                status, error = ("active" if bundle_id == active else "available"), None
            except BundleError as e:
                manifest = {}
                status, error = "invalid", str(e)
            infos.append(BundleInfo(bundle_id, path, status, error, manifest))
        return infos

    def activate(self, bundle_id: str, actor: str | None = None):
        """Verify the bundle, then make it active. Returns the loaded bundle."""
        if bundle_id not in self.bundle_ids():
            raise BundleError(f"No bundle '{bundle_id}' in {self.root}")
        bundle = load_bundle(self.root / bundle_id)  # refuse invalid bundles before switching

        state = self.state()
        state["history"].append({
            "bundle_id": bundle_id,
            "previous": state["active"],
            "activated_at": datetime.now().isoformat(timespec="seconds"),
            "by": actor or getpass.getuser(),
        })
        state["active"] = bundle_id
        self._write_state(state)
        return bundle

    def rollback(self, actor: str | None = None):
        """Re-activate the bundle that was active before the current one."""
        state = self.state()
        previous = next((h["previous"] for h in reversed(state["history"])
                         if h["bundle_id"] == state["active"]), None)
        if previous is None:
            raise BundleError("Nothing to roll back to")
        return self.activate(previous, actor)
