"""
Manage the server's model bundles in model_store/.

Without --db, the active bundle is recorded in model_store/registry.json (offline use).
The web server reads it from its database instead: use --db there, e.g. inside the container:
    docker compose exec api python scripts/manage_models.py --db rescan
    docker compose exec api python scripts/manage_models.py --db activate <bundle_id>
"""
import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.inference.bundle import load_bundle, BundleError
from src.inference.store import ModelStore


def _summary(manifest):
    test = manifest.get("metrics", {}).get("test", {})
    mc, bv, os_ = test.get("multiclass", {}), test.get("attack_vs_benign", {}), test.get("open_set", {})
    latency = manifest.get("latency_cpu", {})
    return (f"macro-F1 {mc.get('macro_f1', float('nan')):.4f} | attack recall {bv.get('recall_attack', float('nan')):.4f} | "
            f"benign->unknown {os_.get('benign_as_unknown', float('nan')):.2%} | "
            f"10k flows {latency.get('batch_ms_median', '?')} ms")


def cmd_list(store, _args):
    infos = store.scan()
    if not infos:
        print(f"  No bundles in {store.root}. Build one: python scripts/build_bundle.py --exp EXP-59")
        return
    for info in infos:
        mark = "*" if info.status == "active" else " "
        print(f" {mark} {info.bundle_id:<42} {info.status:<9} "
              + (_summary(info.manifest) if info.status != "invalid" else info.error))
    if store.active_id() is None:
        print("  No active bundle. Activate one: python scripts/manage_models.py activate <bundle_id>")


def cmd_activate(store, args):
    previous = store.active_id()
    bundle = store.activate(args.bundle_id)
    print(f"  Active: {bundle.bundle_id} (was {previous})")


def cmd_rollback(store, _args):
    previous = store.active_id()
    bundle = store.rollback()
    print(f"  Rolled back: {previous} -> {bundle.bundle_id}")


def cmd_verify(store, args):
    bundle = load_bundle(store.root / args.bundle_id)
    print(f"  OK: {bundle.bundle_id} (format, hashes, library versions, "
          f"self-test on {bundle.manifest['selftest_rows']} rows)")


# ── --db: the web server's model_versions table ──

def db_list(registry, db, _args):
    from sqlalchemy import select
    from src.api.db.models import ModelVersion

    rows = db.scalars(select(ModelVersion).order_by(ModelVersion.registered_at)).all()
    if not rows:
        print("  No registered versions. Register the bundles: python scripts/manage_models.py --db rescan")
    for row in rows:
        mark = "*" if row.status == "active" else " "
        detail = _summary(row.manifest) if row.status in ("active", "available") else row.invalid_reason
        print(f" {mark} {row.bundle_id:<42} {row.status:<9} {detail}")
        if row.status == "active" and row.invalid_reason:
            print(f"    warning: {row.invalid_reason}")


def db_rescan(registry, db, _args):
    report = registry.rescan(db, actor_id=None)
    for name, ids in report.__dict__.items():
        print(f"  {name:<9} {', '.join(ids) or '-'}")


def _switched(activation):
    from src.api.runtime import model_events
    from src.api.settings import get_settings

    if not activation.changed:
        print(f"  {activation.version.bundle_id} is already active")
        return
    settings = get_settings()
    notified = settings.model_events_enabled and model_events.publish(
        settings.redis_url, {"type": "activated", "bundle_id": activation.version.bundle_id,
                             "version_id": activation.version.id})
    print(f"  Active: {activation.version.bundle_id} (was {activation.previous}); "
          + ("servers notified" if notified else f"servers switch within {settings.model_poll_seconds:.0f} s"))


def db_activate(registry, db, args):
    from sqlalchemy import select
    from src.api.db.models import ModelVersion

    version_id = db.scalar(select(ModelVersion.id).where(ModelVersion.bundle_id == args.bundle_id))
    if version_id is None:
        sys.exit(f"  {args.bundle_id} is not registered; run: python scripts/manage_models.py --db rescan")
    _switched(registry.activate(db, version_id, actor_id=None))


def db_rollback(registry, db, _args):
    _switched(registry.rollback(db, actor_id=None))


def run_db(args):
    from src.api.db.session import get_sessionmaker
    from src.api.runtime.model_registry import ModelRegistry, RegistryError

    commands = {"list": db_list, "rescan": db_rescan, "activate": db_activate, "rollback": db_rollback,
                "verify": lambda registry, _db, a: cmd_verify(ModelStore(registry.root), a)}
    registry = ModelRegistry(args.store, get_sessionmaker())
    with get_sessionmaker()() as db:
        try:
            commands[args.command](registry, db, args)
        except RegistryError as e:
            sys.exit(f"  Error: {e.message}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage model bundles for the IDS server")
    parser.add_argument("--store", default=str(PROJECT_ROOT / "model_store"),
                        help="Model store directory (default: model_store/)")
    parser.add_argument("--db", action="store_true",
                        help="Use the web server's database (IDS_DATABASE_URL) instead of registry.json")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="Show every bundle with its metrics (without --db: verifies them too)")
    sub.add_parser("rescan", help="--db only: register new bundles, re-check known ones")
    p = sub.add_parser("activate", help="Verify a bundle and make it the active one")
    p.add_argument("bundle_id")
    sub.add_parser("rollback", help="Re-activate the previously active bundle")
    p = sub.add_parser("verify", help="Fully verify one bundle")
    p.add_argument("bundle_id")
    args = parser.parse_args()

    commands = {"list": cmd_list, "activate": cmd_activate, "rollback": cmd_rollback, "verify": cmd_verify}
    try:
        if args.db:
            run_db(args)
        elif args.command == "rescan":
            sys.exit("  rescan needs --db (without it, list already verifies every bundle)")
        else:
            commands[args.command](ModelStore(args.store), args)
    except BundleError as e:
        sys.exit(f"  Error: {e}")
