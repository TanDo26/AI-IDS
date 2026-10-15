"""
Bundle loading checks, the model store (activate / rollback) and the per-process model manager.
"""

import json
import shutil
import time

import pandas as pd
import pytest

from src.inference.bundle import FORMAT_VERSION, MANIFEST, BundleError, load_bundle
from src.inference.manager import ModelManager
from tests.conftest import TINY_A, TINY_B
from tests.tiny_bundle import CANONICAL_FLOWS, CONSTANT_FEATURE, PORTSCAN


@pytest.fixture
def bundle_dir(tmp_path, tiny_bundles):
    return shutil.copytree(tiny_bundles[TINY_A], tmp_path / TINY_A)


def edit_manifest(path, change):
    manifest = json.loads((path / MANIFEST).read_text(encoding="utf-8"))
    change(manifest)
    (path / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")


def tamper(path, name="classifier.pkl"):
    (path / name).write_bytes(b"not a pickle")


# ── loading ─────────────────────────────────────────────────

def test_load_verified_bundle(bundle_dir):
    bundle = load_bundle(bundle_dir)
    assert bundle.bundle_id == TINY_A
    assert bundle.manifest["format"] == FORMAT_VERSION
    assert CONSTANT_FEATURE not in bundle.manifest["required_features"]    # dropped by the selector
    assert len(bundle.predict(pd.DataFrame([f for f, *_ in CANONICAL_FLOWS.values()]))) == len(CANONICAL_FLOWS)


def test_hashes_are_checked_before_unpickling(bundle_dir):
    tamper(bundle_dir)
    with pytest.raises(BundleError, match="classifier.pkl does not match its SHA-256"):
        load_bundle(bundle_dir)


def test_missing_file(bundle_dir):
    (bundle_dir / "anomaly_detector.pkl").unlink()
    with pytest.raises(BundleError, match="missing file anomaly_detector.pkl"):
        load_bundle(bundle_dir)


def test_missing_manifest(bundle_dir):
    (bundle_dir / MANIFEST).unlink()
    with pytest.raises(BundleError, match="no manifest.json"):
        load_bundle(bundle_dir)


def test_other_format_versions_are_refused(bundle_dir):
    edit_manifest(bundle_dir, lambda m: m.update(format=FORMAT_VERSION - 1))
    with pytest.raises(BundleError, match="rebuild it"):
        load_bundle(bundle_dir)


def test_library_major_minor_must_match(bundle_dir):
    edit_manifest(bundle_dir, lambda m: m["versions"].update({"scikit-learn": "0.1.0"}))
    with pytest.raises(BundleError, match="built with scikit-learn 0.1.0"):
        load_bundle(bundle_dir)


def test_selftest_catches_edited_thresholds(bundle_dir):
    # The manifest is not hashed; the self-test notices that decisions changed
    edit_manifest(bundle_dir, lambda m: m["open_set"]["thresholds"]["known_per_class"].update({str(PORTSCAN): 0.5}))
    with pytest.raises(BundleError, match="self-test failed.*decisions"):
        load_bundle(bundle_dir)
    assert load_bundle(bundle_dir, verify=False).bundle_id == TINY_A


# ── store ───────────────────────────────────────────────────

def test_scan_reports_each_bundle(model_store, install_bundle):
    install_bundle(TINY_A)
    tamper(install_bundle(TINY_B, activate=False))
    infos = {i.bundle_id: i for i in model_store.scan()}
    assert infos[TINY_A].status == "active"
    assert infos[TINY_B].status == "invalid" and "SHA-256" in infos[TINY_B].error


def test_activate_refuses_unknown_and_invalid_bundles(model_store, install_bundle):
    install_bundle(TINY_A)
    with pytest.raises(BundleError, match="No bundle"):
        model_store.activate("nope")
    tamper(install_bundle(TINY_B, activate=False))
    with pytest.raises(BundleError):
        model_store.activate(TINY_B)
    assert model_store.active_id() == TINY_A


def test_rollback(model_store, install_bundle):
    with pytest.raises(BundleError, match="Nothing to roll back to"):
        model_store.rollback()
    install_bundle(TINY_A)
    install_bundle(TINY_B)
    model_store.rollback(actor="pytest")
    assert model_store.active_id() == TINY_A
    history = model_store.state()["history"]
    assert [(h["bundle_id"], h["previous"]) for h in history] == [(TINY_A, None), (TINY_B, TINY_A), (TINY_A, TINY_B)]


# ── manager ─────────────────────────────────────────────────

def test_manager_follows_the_store(model_store, install_bundle):
    manager = ModelManager(model_store)
    assert manager.ensure_current() is None and manager.engine() is None

    install_bundle(TINY_A)
    old = manager.ensure_current()
    assert old.bundle_id == TINY_A and manager.engine().bundle is old

    install_bundle(TINY_B)
    assert manager.ensure_current().bundle_id == TINY_B
    # Work that already holds the old bundle finishes on it
    assert len(old.predict(pd.DataFrame([CANONICAL_FLOWS["ddos"][0]]))) == 1
    status = manager.status()
    assert status["loaded"] == status["active_in_store"] == TINY_B and status["last_error"] is None


def test_manager_keeps_serving_when_the_new_bundle_fails(model_store, install_bundle):
    manager = ModelManager(model_store)
    install_bundle(TINY_A)
    manager.ensure_current()
    tamper(install_bundle(TINY_B, activate=False))
    model_store._write_state({**model_store.state(), "active": TINY_B})   # pointer moved behind activate()'s back

    assert manager.ensure_current().bundle_id == TINY_A
    assert TINY_B in manager.status()["last_error"]


def test_polling_picks_up_a_switch(model_store, install_bundle):
    install_bundle(TINY_A)
    manager = ModelManager(model_store)
    manager.ensure_current()
    manager.start_polling(interval_s=0.05)
    try:
        install_bundle(TINY_B)
        deadline = time.monotonic() + 10
        while manager.current().bundle_id != TINY_B and time.monotonic() < deadline:
            time.sleep(0.05)
        assert manager.current().bundle_id == TINY_B
    finally:
        manager.stop_polling()
