"""
Model versions in the database: which bundles in model_store/ are registered, valid and active.

For the web server the `model_versions` table, not model_store/registry.json, says which bundle
is active (registry.json is only used by scripts/manage_models.py without --db). Every process
loads <model_store>/<bundle_id> of the active version.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.api.db.models import AuditLog, ModelVersion
from src.inference.bundle import BundleError, load_bundle, verify_files
from src.inference.store import ModelStore

NOT_IN_STORE = "Not found in the model store"


class RegistryError(Exception):
    """Maps to an HTTP error: status + message."""

    def __init__(self, status: int, message: str):
        self.status, self.message = status, message
        super().__init__(message)


@dataclass
class RescanReport:
    added: list[str] = field(default_factory=list)
    verified: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)


@dataclass
class Activation:
    version: ModelVersion
    previous: str | None          # bundle id active before the switch (None if none, or no switch)
    changed: bool                 # False when the version was already active


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ModelRegistry:

    def __init__(self, root, session_factory: sessionmaker[Session]):
        self.root = Path(root)
        self._session_factory = session_factory

    # ── read side: used by every process's ModelManager ──

    def active_id(self) -> str | None:
        with self._session_factory() as db:
            return db.scalar(select(ModelVersion.bundle_id).where(ModelVersion.status == "active"))

    # ── admin operations (callers pass their session; actor_id None = a CLI) ──

    def _check(self, bundle_id: str, full: bool) -> dict:
        """Verify a bundle; full loads it and runs its self-test. Returns the manifest."""
        path = self.root / bundle_id
        manifest = load_bundle(path).manifest if full else verify_files(path)
        if manifest.get("bundle_id") != bundle_id:
            # The manager compares ids: a renamed directory would be reloaded on every check
            raise BundleError(f"{bundle_id}: directory name differs from the manifest's bundle_id "
                              f"'{manifest.get('bundle_id')}'")
        return manifest

    def rescan(self, db: Session, actor_id: int | None) -> RescanReport:
        """Register new bundles, re-check known ones, retire the ones no longer on disk.

        New bundles and ones that failed before get a full load + self-test. Registered, healthy
        ones only get their files re-hashed: the self-test can't change unless their files or the
        library versions do, and both are checked. The active version keeps serving whatever is
        found; problems with it are recorded in invalid_reason.
        """
        if not self.root.is_dir():
            # A missing mount looks like an empty store, which would retire every registered bundle
            raise RegistryError(503, f"The model store {self.root} doesn't exist or isn't mounted; nothing was changed")
        on_disk = ModelStore(self.root).bundle_ids()
        rows = {v.bundle_id: v for v in db.scalars(select(ModelVersion))}
        report = RescanReport()

        for bundle_id in on_disk:
            row = rows.get(bundle_id)
            try:
                manifest, error = self._check(bundle_id, full=row is None or row.status in ("invalid", "retired")), None
            except BundleError as e:
                manifest, error = None, str(e)

            if row is None:
                row = ModelVersion(bundle_id=bundle_id, path=str(self.root / bundle_id), manifest=manifest or {})
                db.add(row)
                report.added.append(bundle_id)
            elif manifest is not None:
                row.manifest = manifest
            row.path = str(self.root / bundle_id)
            if row.status != "active":
                row.status = "available" if error is None else "invalid"
            row.invalid_reason = error
            (report.invalid if error else report.verified).append(bundle_id)

        for bundle_id, row in rows.items():
            if bundle_id not in on_disk and row.invalid_reason != NOT_IN_STORE:
                if row.status != "active":
                    row.status = "retired"
                row.invalid_reason = NOT_IN_STORE
                report.retired.append(bundle_id)

        db.add(AuditLog(actor_id=actor_id, action="model.rescan", target_type="model_store",
                        target_id=self.root.name, details=report.__dict__))
        db.commit()
        return report

    def activate(self, db: Session, version_id: int, actor_id: int | None,
                 action: str = "model.activate") -> Activation:
        """Verify the version's bundle, then make it the only active one, in one transaction."""
        target = db.get(ModelVersion, version_id)
        if target is None:
            raise RegistryError(404, f"No model version {version_id}")
        if target.status == "active":
            return Activation(target, None, changed=False)
        if target.status != "available":
            raise RegistryError(409, f"{target.bundle_id} is {target.status}: {target.invalid_reason}. "
                                     f"Fix or rebuild it, then rescan.")
        try:
            target.manifest = self._check(target.bundle_id, full=True)  # never switch to a failing bundle
        except BundleError as e:
            target.status, target.invalid_reason = "invalid", str(e)
            db.commit()
            raise RegistryError(409, f"{target.bundle_id} failed verification: {e}")

        previous = active_version(db)
        if previous is not None:
            previous.status = "available"
            db.flush()   # demote first: the database allows only one active version
        target.status, target.activated_at, target.activated_by = "active", _now(), actor_id
        target.invalid_reason = None
        db.add(AuditLog(actor_id=actor_id, action=action, target_type="model_version", target_id=str(target.id),
                        details={"bundle_id": target.bundle_id,
                                 "previous": previous.bundle_id if previous else None}))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise RegistryError(409, "Another model switch happened at the same time; reload and try again")
        return Activation(target, previous.bundle_id if previous else None, changed=True)

    def rollback(self, db: Session, actor_id: int | None) -> Activation:
        """Re-activate the most recently active version other than the current one."""
        previous = db.scalar(select(ModelVersion)
                             .where(ModelVersion.status == "available", ModelVersion.activated_at.is_not(None))
                             .order_by(ModelVersion.activated_at.desc())
                             .limit(1))
        if previous is None:
            raise RegistryError(409, "Nothing to roll back to")
        return self.activate(db, previous.id, actor_id, action="model.rollback")


def active_version(db: Session) -> ModelVersion | None:
    return db.scalar(select(ModelVersion).where(ModelVersion.status == "active"))
