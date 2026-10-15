"""
Rate limits, the secret-key rules in settings, and scripts/create_admin.py.
"""

import importlib.util
import os

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from src.api import ratelimit
from src.api.auth.security import verify_password
from src.api.db.models import AuditLog, User
from src.api.ratelimit import LOGIN_PER_IP, RateLimiter
from src.api.settings import DEV_SECRET_KEY, get_settings
from tests.conftest import PROJECT_ROOT
from tests.helpers import API, PASSWORD

# ── rate limits ─────────────────────────────────────────────


def test_limit_counts_per_key():
    limiter = RateLimiter(None)
    for _ in range(2):
        limiter.check("2/minute", "login", "1.2.3.4")
    with pytest.raises(HTTPException) as exc:
        limiter.check("2/minute", "login", "1.2.3.4")
    assert exc.value.status_code == 429
    assert 1 <= int(exc.value.headers["Retry-After"]) <= 60
    limiter.check("2/minute", "login", "5.6.7.8")      # another key has its own budget


def test_unreachable_redis_falls_back_to_memory(caplog):
    limiter = RateLimiter("redis://127.0.0.1:1/0")      # nothing listens on port 1
    limiter.check("1/minute", "k")
    with pytest.raises(HTTPException):
        limiter.check("1/minute", "k")
    assert "using in-memory limits" in caplog.text


@pytest.mark.skipif(not os.environ.get("IDS_TEST_REDIS_URL"), reason="needs IDS_TEST_REDIS_URL")
def test_redis_limits_are_shared_between_processes():
    url = os.environ["IDS_TEST_REDIS_URL"]
    key = os.urandom(8).hex()
    RateLimiter(url).check("1/minute", key)
    with pytest.raises(HTTPException):
        RateLimiter(url).check("1/minute", key)       # a second "process" sees the first one's hit


def test_login_is_rate_limited_per_ip(client, db, override_settings, monkeypatch):
    override_settings(rate_limits_enabled=True)
    limiter = RateLimiter(None)                         # memory only: no Redis needed
    monkeypatch.setattr(ratelimit, "get_rate_limiter", lambda: limiter)

    allowed = int(LOGIN_PER_IP.split("/")[0])
    body = {"email": "nobody@example.com", "password": PASSWORD}
    for _ in range(allowed):
        assert client.post(f"{API}/auth/login", json=body).status_code == 401
    r = client.post(f"{API}/auth/login", json=body)
    assert r.status_code == 429 and "Retry-After" in r.headers


# ── settings ────────────────────────────────────────────────

@pytest.mark.parametrize("secret", [DEV_SECRET_KEY, "too-short"])
def test_production_refuses_a_weak_secret(override_settings, secret):
    override_settings(env="production", secret_key=secret)
    with pytest.raises(RuntimeError, match="IDS_SECRET_KEY"):
        get_settings()


def test_development_warns_about_a_weak_secret(override_settings):
    override_settings(env="development", secret_key=DEV_SECRET_KEY)
    with pytest.warns(UserWarning, match="IDS_SECRET_KEY"):
        get_settings()


def test_production_accepts_a_strong_secret(override_settings):
    override_settings(env="production", secret_key="s" * 48)
    assert get_settings().env == "production"


# ── scripts/create_admin.py ─────────────────────────────────

@pytest.fixture
def create_admin(monkeypatch):
    monkeypatch.setenv("IDS_ADMIN_PASSWORD", "admin-password-123")
    spec = importlib.util.spec_from_file_location("create_admin", PROJECT_ROOT / "scripts" / "create_admin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


def test_create_admin(db, create_admin):
    create_admin(" Root@Example.com", "root", promote=False)
    admin = db.scalar(select(User))
    assert (admin.email, admin.role) == ("root@example.com", "admin")
    assert verify_password("admin-password-123", admin.password_hash)
    audit = db.scalar(select(AuditLog))
    assert audit.action == "user.create_admin" and audit.target_id == str(admin.id)


def test_create_admin_refuses_an_existing_email(user, create_admin):
    with pytest.raises(SystemExit, match="already exists"):
        create_admin(user.email, "another", promote=False)


def test_promote(db, user, create_admin):
    create_admin(user.email, None, promote=True)
    db.refresh(user)
    assert user.role == "admin"
    assert db.scalar(select(AuditLog.action)) == "user.promote"


def test_promote_unknown_user(db, create_admin):
    with pytest.raises(SystemExit, match="No user"):
        create_admin("ghost@example.com", None, promote=True)


def test_create_admin_validates_the_password(db, create_admin, monkeypatch):
    monkeypatch.setenv("IDS_ADMIN_PASSWORD", "short")
    with pytest.raises(SystemExit, match="Password"):
        create_admin("root@example.com", "root", promote=False)
    assert db.scalar(select(User)) is None
