"""
Manage the server's model bundles in model_store/.
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage model bundles for the IDS server")
    parser.add_argument("--store", default=str(PROJECT_ROOT / "model_store"),
                        help="Model store directory (default: model_store/)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="Verify every bundle and show its metrics")
    p = sub.add_parser("activate", help="Verify a bundle and make it the active one")
    p.add_argument("bundle_id")
    sub.add_parser("rollback", help="Re-activate the previously active bundle")
    p = sub.add_parser("verify", help="Fully verify one bundle")
    p.add_argument("bundle_id")
    args = parser.parse_args()

    commands = {"list": cmd_list, "activate": cmd_activate, "rollback": cmd_rollback, "verify": cmd_verify}
    try:
        commands[args.command](ModelStore(args.store), args)
    except BundleError as e:
        sys.exit(f"  Error: {e}")
