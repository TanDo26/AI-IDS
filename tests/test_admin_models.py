"""
Model versions in the database: /admin/models (list, rescan, activate, rollback), processes
picking up a switch, Celery workers, and scripts/manage_models.py --db.
"""

import argparse
import importlib.util
import os
import shutil
import time

import pytest
from sqlalchemy import func, select

from src.api.db.models import AuditLog, ModelVersion
from src.api.db.session import get_sessionmaker
from src.api.runtime import model_events
from src.api.runtime.model_manager import ModelRuntime
from src.api.runtime.model_registry import NOT_IN_STORE, ModelRegistry
from src.api.settings import get_settings
from src.inference.manager import ModelManager
from tests.conftest import PROJECT_ROOT, TINY_A, TINY_B
from tests.helpers import API, bearer, csrf, login
from tests.tiny_bundle import BENIGN, flow

MODELS = f"{API}/admin/models"
needs_redis = pytest.mark.skipif(not os.environ.get("IDS_TEST_REDIS_URL"), reason="needs IDS_TEST_REDIS_URL")


def versions(db) -> dict[str, ModelVersion]:
    db.expire_all()
    return {v.bundle_id: v for v in db.scalars(select(ModelVersion))}


def statuses(db) -> dict[str, str]:
    return {bundle_id: v.status for bundle_id, v in versions(db).items()}


def last_audit(db) -> AuditLog:
    return db.scalars(select(AuditLog).order_by(AuditLog.id.desc())).first()


def tamper(path):
    (path / "classifier.pkl").write_bytes(b"not a pickle")


def wait_for(condition, timeout_s=10.0):
    deadline = time.monotonic() + timeout_s
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.05)
    return condition()


# ── access ──────────────────────────────────────────────────

def test_admin_only(client, user):
    assert client.get(MODELS).status_code == 401
    assert client.get(MODELS, headers=bearer(user)).status_code == 403
    assert client.post(f"{MODELS}/rescan", headers=bearer(user)).status_code == 403


def test_cookie_sessions_need_csrf(client, admin):
    login(client, admin.email)
    assert client.get(MODELS).status_code == 200
    assert client.post(f"{MODELS}/rescan").status_code == 403
    assert client.post(f"{MODELS}/rescan", headers=csrf(client)).status_code == 200


# ── rescan ──────────────────────────────────────────────────

def test_rescan_registers_bundles(client, admin, install_bundle, db):
    install_bundle(TINY_A, activate=False)
    install_bundle(TINY_B, activate=False)
    r = client.post(f"{MODELS}/rescan", headers=bearer(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["added"] == [TINY_A, TINY_B] and body["invalid"] == [] and body["retired"] == []
    assert statuses(db) == {TINY_A: "available", TINY_B: "available"}

    version = next(v for v in body["versions"] if v["bundle_id"] == TINY_A)
    assert version["classes"] == ["Benign", "DDoS", "PortScan"] and version["n_features"] == 6
    assert version["metrics"]["macro_f1"] == 0.99 and version["metrics"]["latency_p95_ms"] == 3.0
    assert version["source"]["model"] == "random_forest"
    audit = last_audit(db)
    assert (audit.action, audit.actor_id) == ("model.rescan", admin.id)
    assert audit.details["added"] == [TINY_A, TINY_B]

    again = client.post(f"{MODELS}/rescan", headers=bearer(admin)).json()
    assert again["added"] == [] and again["verified"] == [TINY_A, TINY_B]
    assert len(versions(db)) == 2


def test_rescan_marks_broken_bundles_invalid(client, admin, install_bundle, model_store, db):
    tamper(install_bundle(TINY_A, activate=False))
    shutil.copytree(install_bundle(TINY_B, activate=False), model_store.root / "renamed")
    body = client.post(f"{MODELS}/rescan", headers=bearer(admin)).json()
    assert body["invalid"] == ["renamed", TINY_A] and body["verified"] == [TINY_B]
    rows = versions(db)
    assert rows[TINY_A].status == "invalid" and "SHA-256" in rows[TINY_A].invalid_reason
    assert "directory name differs" in rows["renamed"].invalid_reason


def test_rescan_rechecks_registered_bundles(db, register_bundle, registry, model_store, tiny_bundles):
    register_bundle(TINY_A, activate=False)
    path = model_store.root / TINY_A
    tamper(path)
    assert registry.rescan(db, None).invalid == [TINY_A]
    assert statuses(db)[TINY_A] == "invalid"

    shutil.rmtree(path)
    shutil.copytree(tiny_bundles[TINY_A], path)              # rebuilt / restored
    assert registry.rescan(db, None).verified == [TINY_A]
    assert versions(db)[TINY_A].status == "available" and versions(db)[TINY_A].invalid_reason is None


def test_rescan_retires_missing_bundles(db, register_bundle, registry, model_store, tiny_bundles):
    register_bundle(TINY_A, activate=False)
    shutil.rmtree(model_store.root / TINY_A)
    assert registry.rescan(db, None).retired == [TINY_A]
    assert (versions(db)[TINY_A].status, versions(db)[TINY_A].invalid_reason) == ("retired", NOT_IN_STORE)
    assert registry.rescan(db, None).retired == []           # reported once

    shutil.copytree(tiny_bundles[TINY_A], model_store.root / TINY_A)
    registry.rescan(db, None)
    assert statuses(db)[TINY_A] == "available"


def test_the_active_version_keeps_serving_when_its_files_break(db, register_bundle, registry, model_store):
    register_bundle(TINY_A)
    tamper(model_store.root / TINY_A)
    registry.rescan(db, None)
    row = versions(db)[TINY_A]
    assert row.status == "active" and "SHA-256" in row.invalid_reason

    shutil.rmtree(model_store.root / TINY_A)
    registry.rescan(db, None)
    row = versions(db)[TINY_A]
    assert row.status == "active" and row.invalid_reason == NOT_IN_STORE


# ── activate ────────────────────────────────────────────────

def test_activate_switches_the_serving_model(client, admin, register_bundle, db):
    register_bundle(TINY_A)
    b = register_bundle(TINY_B, activate=False)
    assert client.app.state.models.ensure_current().bundle_id == TINY_A

    r = client.post(f"{MODELS}/{b.id}/activate", headers=bearer(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["version"]["status"] == "active" and body["version"]["activated_by"] == admin.id
    assert (body["previous"], body["changed"], body["notified"]) == (TINY_A, True, False)
    assert statuses(db) == {TINY_A: "available", TINY_B: "active"}

    audit = last_audit(db)
    assert (audit.action, audit.actor_id, audit.target_id) == ("model.activate", admin.id, str(b.id))
    assert audit.details == {"bundle_id": TINY_B, "previous": TINY_A}

    # The answering process switched straight away; predictions name the new bundle
    assert client.app.state.models.current().bundle_id == TINY_B
    assert client.post(f"{API}/predict", json={"features": flow(BENIGN)},
                       headers=bearer(admin)).json()["bundle_id"] == TINY_B


def test_activating_the_active_version_changes_nothing(client, admin, register_bundle, db):
    a = register_bundle(TINY_A)
    audits = db.scalar(select(func.count()).select_from(AuditLog))
    body = client.post(f"{MODELS}/{a.id}/activate", headers=bearer(admin)).json()
    assert body["changed"] is False and body["version"]["status"] == "active"
    assert db.scalar(select(func.count()).select_from(AuditLog)) == audits


def test_cannot_activate_unknown_or_invalid_versions(client, admin, install_bundle, registry, db):
    tamper(install_bundle(TINY_A, activate=False))
    registry.rescan(db, None)
    assert client.post(f"{MODELS}/9999/activate", headers=bearer(admin)).status_code == 404
    r = client.post(f"{MODELS}/{versions(db)[TINY_A].id}/activate", headers=bearer(admin))
    assert r.status_code == 409 and "invalid" in r.json()["detail"]


def test_activation_verifies_the_bundle_first(client, admin, register_bundle, model_store, db):
    register_bundle(TINY_A)
    b = register_bundle(TINY_B, activate=False)
    tamper(model_store.root / TINY_B)                         # broken after the last rescan
    r = client.post(f"{MODELS}/{b.id}/activate", headers=bearer(admin))
    assert r.status_code == 409 and "failed verification" in r.json()["detail"]
    assert statuses(db) == {TINY_A: "active", TINY_B: "invalid"}


def test_rollback(client, admin, register_bundle, db):
    register_bundle(TINY_A)
    assert client.post(f"{MODELS}/rollback", headers=bearer(admin)).status_code == 409   # nothing before A
    register_bundle(TINY_B)

    r = client.post(f"{MODELS}/rollback", headers=bearer(admin))
    assert r.status_code == 200
    assert (r.json()["version"]["bundle_id"], r.json()["previous"]) == (TINY_A, TINY_B)
    assert statuses(db) == {TINY_A: "active", TINY_B: "available"}
    assert last_audit(db).action == "model.rollback"
    assert client.app.state.models.current().bundle_id == TINY_A

    client.post(f"{MODELS}/rollback", headers=bearer(admin))   # and back again
    assert statuses(db) == {TINY_A: "available", TINY_B: "active"}


def test_overview(client, admin, register_bundle, db):
    register_bundle(TINY_A)
    register_bundle(TINY_B, activate=False)
    client.app.state.models.ensure_current()
    body = client.get(MODELS, headers=bearer(admin)).json()
    assert body["active"] == TINY_A
    assert {v["bundle_id"] for v in body["versions"]} == {TINY_A, TINY_B}
    assert body["this_process"]["loaded"] == body["this_process"]["active_in_store"] == TINY_A
    assert body["processes"] is None                          # model events are off in tests


# ── propagation to other processes ──────────────────────────

def test_another_process_picks_up_a_switch_by_polling(override_settings, register_bundle, db):
    override_settings(model_poll_seconds=0.05)
    register_bundle(TINY_A)
    other = ModelManager(ModelRegistry(get_settings().model_store, get_sessionmaker()))   # "another process"
    runtime = ModelRuntime(other, get_settings(), kind="api", listen=False)
    runtime.start()
    try:
        assert wait_for(lambda: other.current() is not None and other.current().bundle_id == TINY_A)
        register_bundle(TINY_B)
        assert wait_for(lambda: other.current().bundle_id == TINY_B)
    finally:
        runtime.stop()


@needs_redis
def test_another_process_switches_on_the_event(override_settings, register_bundle, db):
    url = os.environ["IDS_TEST_REDIS_URL"]
    override_settings(model_events_enabled=True, redis_url=url, model_poll_seconds=3600)
    register_bundle(TINY_A)
    other = ModelManager(ModelRegistry(get_settings().model_store, get_sessionmaker()))
    runtime = ModelRuntime(other, get_settings(), kind="api", listen=True)
    runtime.start()
    try:
        assert wait_for(lambda: other.current() is not None)     # subscribed and caught up
        time.sleep(0.2)
        register_bundle(TINY_B)
        assert model_events.publish(url, {"type": "activated", "bundle_id": TINY_B})
        assert wait_for(lambda: other.current().bundle_id == TINY_B, timeout_s=5)

        reports = {r["process"]: r for r in model_events.loaded_by_process(url)}
        assert reports[model_events.process_id()]["kind"] == "api"
    finally:
        runtime.stop()
    assert model_events.process_id() not in {r["process"] for r in model_events.loaded_by_process(url)}


@needs_redis
def test_overview_lists_lagging_processes(client, admin, register_bundle, override_settings, db):
    url = os.environ["IDS_TEST_REDIS_URL"]
    override_settings(model_events_enabled=True, redis_url=url)
    register_bundle(TINY_B)
    status = {"loaded": TINY_A, "loaded_at": None, "active_in_store": TINY_B, "last_error": None}
    model_events.report_loaded(url, "worker", status, ttl_s=60)
    try:
        processes = client.get(MODELS, headers=bearer(admin)).json()["processes"]
        mine = next(p for p in processes if p["process"] == model_events.process_id())
        assert mine["lagging"] is True and mine["kind"] == "worker"
    finally:
        model_events.clear_report(url)


# ── Celery worker ───────────────────────────────────────────

def test_worker_switches_at_the_start_of_each_job(register_bundle, monkeypatch):
    from src.api.worker import tasks
    monkeypatch.setattr(tasks, "_models", None)
    register_bundle(TINY_A)
    assert tasks.ping() == {"pong": True, "model": TINY_A}
    register_bundle(TINY_B)
    assert tasks.ping() == {"pong": True, "model": TINY_B}


def test_worker_process_loads_the_bundle_in_the_background(register_bundle, monkeypatch):
    from src.api.worker import tasks
    monkeypatch.setattr(tasks, "_models", None)
    monkeypatch.setattr(tasks, "_runtime", None)
    register_bundle(TINY_A)
    tasks._start_model_runtime()              # worker_process_init: returns before the bundle is loaded
    try:
        assert wait_for(lambda: tasks._models.current() is not None)
        assert tasks._models.current().bundle_id == TINY_A
    finally:
        tasks._stop_model_runtime()


# ── scripts/manage_models.py --db ───────────────────────────

@pytest.fixture
def manage_models():
    spec = importlib.util.spec_from_file_location("manage_models", PROJECT_ROOT / "scripts" / "manage_models.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def run(command, bundle_id=None):
        module.run_db(argparse.Namespace(store=str(get_settings().model_store), db=True,
                                         command=command, bundle_id=bundle_id))
    return run


def test_cli_db_commands(manage_models, install_bundle, db, capsys):
    install_bundle(TINY_A, activate=False)
    install_bundle(TINY_B, activate=False)
    manage_models("rescan")
    assert statuses(db) == {TINY_A: "available", TINY_B: "available"}

    manage_models("activate", TINY_A)
    manage_models("activate", TINY_B)
    assert "Active: tiny-b (was tiny-a)" in capsys.readouterr().out
    manage_models("rollback")
    assert statuses(db) == {TINY_A: "active", TINY_B: "available"}
    assert last_audit(db).actor_id is None

    manage_models("list")
    assert "* tiny-a" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="not registered"):
        manage_models("activate", "nope")
