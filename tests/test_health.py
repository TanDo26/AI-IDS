"""
/healthz, /readyz and the X-Request-ID middleware.
"""

import pytest

from src.api import health
from tests.conftest import TINY_A
from tests.helpers import API


@pytest.fixture
def redis_up(monkeypatch):
    monkeypatch.setattr(health, "_check_redis", lambda url: {"ok": True})


@pytest.fixture
def redis_down(monkeypatch):
    monkeypatch.setattr(health, "_check_redis", lambda url: {"ok": False, "error": "ConnectionError"})


def test_healthz(client):
    r = client.get(f"{API}/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_request_id_is_generated(client):
    rid = client.get(f"{API}/healthz").headers["X-Request-ID"]
    assert len(rid) == 32 and int(rid, 16) >= 0


def test_well_formed_request_id_is_kept(client):
    r = client.get(f"{API}/healthz", headers={"X-Request-ID": "proxy-abc.123_x"})
    assert r.headers["X-Request-ID"] == "proxy-abc.123_x"


@pytest.mark.parametrize("bad", ["has space", "a" * 65, "semi;colon"])
def test_malformed_request_id_is_replaced(client, bad):
    rid = client.get(f"{API}/healthz", headers={"X-Request-ID": bad}).headers["X-Request-ID"]
    assert rid != bad and len(rid) == 32


def test_ready_with_database_redis_and_model(client, redis_up, active_bundle):
    r = client.get(f"{API}/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is True
    assert body["checks"]["database"] == {"ok": True}
    assert body["checks"]["model"]["loaded"] == TINY_A


def test_not_ready_without_an_active_bundle(client, redis_up):
    r = client.get(f"{API}/readyz")
    assert r.status_code == 503
    checks = r.json()["checks"]
    assert checks["model"]["ok"] is False and checks["model"]["loaded"] is None
    assert checks["database"]["ok"] is True


def test_not_ready_when_redis_is_down(client, redis_down, active_bundle):
    r = client.get(f"{API}/readyz")
    assert r.status_code == 503
    assert r.json()["checks"]["redis"]["ok"] is False


def test_not_ready_when_database_is_down(client, redis_up, active_bundle, monkeypatch):
    monkeypatch.setattr(health, "_check_database", lambda: {"ok": False, "error": "OperationalError"})
    r = client.get(f"{API}/readyz")
    assert r.status_code == 503
    assert r.json()["checks"]["database"]["ok"] is False
