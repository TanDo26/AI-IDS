"""
/auth: signup, login, tokens, CSRF, refresh rotation, logout, password change, deactivation, admin.
"""

import jwt
import pytest
from fastapi import Depends
from sqlalchemy import select

from src.api.auth import security
from src.api.auth.deps import require_admin
from src.api.db.models import RefreshToken, User
from src.api.settings import get_settings
from tests.helpers import API, PASSWORD, bearer, cookie_header, csrf, login

SESSION_COOKIES = (security.ACCESS_COOKIE, security.REFRESH_COOKIE, security.CSRF_COOKIE)


def signup(client, email="bob@example.com", username="bob", password=PASSWORD):
    return client.post(f"{API}/auth/signup", json={"email": email, "username": username, "password": password})


def refresh(client, token=None, csrf_token=None):
    """POST /auth/refresh with the client's cookies, or with only the given refresh token."""
    if token is None:
        return client.post(f"{API}/auth/refresh", headers=csrf(client))
    csrf_token = csrf_token or "c" * 20
    return client.post(f"{API}/auth/refresh", headers={
        security.CSRF_HEADER: csrf_token,
        **cookie_header(**{security.REFRESH_COOKIE: token, security.CSRF_COOKIE: csrf_token})})


def assert_cookies_cleared(response):
    set_cookie = response.headers.get_list("set-cookie")
    for name in SESSION_COOKIES:
        assert any(h.startswith(f"{name}=") and "Max-Age=0" in h for h in set_cookie), name


# ── signup ──────────────────────────────────────────────────

def test_signup_logs_the_new_user_in(client, db):
    r = signup(client, email="  Bob@Example.COM ")
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["email"] == "bob@example.com"
    assert body["user"]["role"] == "user"
    assert body["user"]["last_login_at"] is not None          # signing up is the first sign-in
    assert body["token_type"] == "bearer" and body["access_token"]
    assert all(client.cookies.get(name) for name in SESSION_COOKIES)
    assert client.get(f"{API}/auth/me").json()["username"] == "bob"


def test_cookie_attributes(client, db):
    set_cookie = {h.split("=", 1)[0]: h for h in signup(client).headers.get_list("set-cookie")}
    for name, path, http_only in [(security.ACCESS_COOKIE, "/api", True),
                                  (security.REFRESH_COOKIE, "/api/v1/auth", True),
                                  (security.CSRF_COOKIE, "/", False)]:
        header = set_cookie[name]
        assert f"Path={path};" in header + ";"
        assert "Secure" in header and "SameSite=lax" in header
        assert ("HttpOnly" in header) is http_only


@pytest.mark.parametrize("field", ["email", "username"])
def test_signup_rejects_taken_email_or_username(client, user, field):
    taken = {"email": user.email, "username": "fresh"} if field == "email" else \
            {"email": "fresh@example.com", "username": user.username}
    r = signup(client, **taken)
    assert r.status_code == 409
    assert field in r.json()["detail"]


@pytest.mark.parametrize("changes", [
    {"email": "not-an-email"},
    {"username": "ab"},
    {"username": "has space"},
    {"password": "short"},
    {"password": "é" * 37},          # 74 bytes: bcrypt would reject it
])
def test_signup_validation(client, db, changes):
    assert signup(client, **changes).status_code == 422


# ── login ───────────────────────────────────────────────────

def test_login_returns_a_bearer_token_and_sets_cookies(client, user, db):
    r = login(client, email=" ALICE@example.com")
    body = r.json()
    assert body["expires_in"] == 15 * 60
    assert body["user"]["id"] == user.id
    assert all(client.cookies.get(name) for name in SESSION_COOKIES)
    db.refresh(user)
    assert user.last_login_at is not None


@pytest.mark.parametrize("email, password", [
    ("alice@example.com", "wrong-password"),
    ("nobody@example.com", PASSWORD),
])
def test_login_failures_look_the_same(client, user, email, password):
    r = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 401
    assert r.json()["detail"] == "Incorrect email or password"


def test_deactivated_user_cannot_log_in(client, make_user):
    make_user(is_active=False)
    r = client.post(f"{API}/auth/login", json={"email": "alice@example.com", "password": PASSWORD})
    assert r.status_code == 403


# ── access tokens ───────────────────────────────────────────

def test_bearer_token_works_without_cookies(client, user):
    r = client.get(f"{API}/auth/me", headers=bearer(user))
    assert r.status_code == 200 and r.json()["email"] == user.email


def test_not_authenticated(client, db):
    r = client.get(f"{API}/auth/me")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"


def _signed(payload):
    return jwt.encode(payload, get_settings().secret_key.get_secret_value(), algorithm="HS256")


@pytest.mark.parametrize("make_token, detail", [
    (lambda u: security.create_access_token(u.id, minutes=-1), "Access token expired"),
    (lambda u: security.create_access_token(u.id)[:-2] + "xx", "Invalid access token"),
    (lambda u: _signed({"sub": str(u.id), "type": "refresh", "exp": 2**31}), "Invalid access token"),
    (lambda u: _signed({"sub": str(u.id), "type": "access"}), "Invalid access token"),       # no exp
    (lambda u: jwt.encode({"sub": str(u.id), "type": "access", "exp": 2**31}, "another-secret-key-of-32-bytes!!",
                          algorithm="HS256"), "Invalid access token"),
])
def test_rejected_access_tokens(client, user, make_token, detail):
    r = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {make_token(user)}"})
    assert r.status_code == 401
    assert r.json()["detail"] == detail


def test_token_of_a_deleted_user(client, user, db):
    headers = bearer(user)
    db.delete(user)
    db.commit()
    r = client.get(f"{API}/auth/me", headers=headers)
    assert r.status_code == 401 and r.headers["WWW-Authenticate"] == "Bearer"


def test_only_credential_failures_ask_for_authentication(client, user):
    # The frontend refreshes the session only on a 401 with WWW-Authenticate. Answers to what the
    # user typed (wrong password, wrong current password) must not carry it, or a typo would
    # rotate the session and could even sign the user out.
    expired = {"Authorization": f"Bearer {security.create_access_token(user.id, minutes=-1)}"}
    for r in (client.get(f"{API}/auth/me"), client.get(f"{API}/auth/me", headers=expired)):
        assert r.status_code == 401 and r.headers["WWW-Authenticate"] == "Bearer"
    for r in (client.post(f"{API}/auth/login", json={"email": user.email, "password": "wrong-password"}),
              client.post(f"{API}/auth/password", headers=bearer(user),
                          json={"current_password": "wrong-password", "new_password": "another-good-password"})):
        assert r.status_code == 401 and "WWW-Authenticate" not in r.headers


# ── CSRF ────────────────────────────────────────────────────

PASSWORD_CHANGE = {"current_password": PASSWORD, "new_password": "another-good-password"}


def test_cookie_requests_need_the_csrf_header(client, user):
    login(client)
    assert client.get(f"{API}/auth/me").status_code == 200            # safe method: no token needed
    r = client.post(f"{API}/auth/password", json=PASSWORD_CHANGE)
    assert r.status_code == 403 and "CSRF" in r.json()["detail"]
    r = client.post(f"{API}/auth/password", json=PASSWORD_CHANGE,
                    headers={security.CSRF_HEADER: "not-the-cookie-value"})
    assert r.status_code == 403
    assert client.post(f"{API}/auth/password", json=PASSWORD_CHANGE, headers=csrf(client)).status_code == 200


def test_bearer_requests_are_exempt_from_csrf(client, user):
    r = client.post(f"{API}/auth/password", json=PASSWORD_CHANGE, headers=bearer(user))
    assert r.status_code == 200


@pytest.mark.parametrize("path", ["/auth/refresh", "/auth/logout"])
def test_refresh_and_logout_need_the_csrf_header(client, user, path):
    login(client)
    assert client.post(f"{API}{path}").status_code == 403


# ── refresh rotation ────────────────────────────────────────

def test_refresh_rotates_the_token(client, user, db):
    old = login(client).cookies[security.REFRESH_COOKIE]
    r = refresh(client)
    assert r.status_code == 200
    new = client.cookies.get(security.REFRESH_COOKIE)
    assert new and new != old
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 200

    tokens = db.scalars(select(RefreshToken)).all()
    assert len(tokens) == 2 and len({t.family_id for t in tokens}) == 1
    assert [t.revoked_at is not None for t in sorted(tokens, key=lambda t: t.id)] == [True, False]


def test_replayed_refresh_token_ends_the_whole_session(client, user, db):
    stolen = login(client).cookies[security.REFRESH_COOKIE]
    assert refresh(client).status_code == 200
    current = client.cookies.get(security.REFRESH_COOKIE)

    replay = refresh(client, token=stolen)
    assert replay.status_code == 401
    assert replay.json()["detail"] == "Session ended; please log in again"
    assert_cookies_cleared(replay)
    # The legitimate holder's newer token is revoked too
    assert refresh(client, token=current).status_code == 401
    assert all(t.revoked_at is not None for t in db.scalars(select(RefreshToken)))


def test_other_sessions_survive_a_replay(client, user):
    other_session = login(client).cookies[security.REFRESH_COOKIE]
    stolen = login(client).cookies[security.REFRESH_COOKIE]
    assert refresh(client).status_code == 200
    assert refresh(client, token=stolen).status_code == 401
    assert refresh(client, token=other_session).status_code == 200


def test_expired_refresh_token(client, user, db):
    token = login(client).cookies[security.REFRESH_COOKIE]
    row = db.scalar(select(RefreshToken))
    row.expires_at = row.expires_at.replace(year=2000)
    db.commit()
    r = refresh(client, token=token)
    assert r.status_code == 401 and "expired" in r.json()["detail"]


@pytest.mark.parametrize("token, detail", [("", "Not logged in"), ("made-up-token", "Session not found")])
def test_refresh_without_a_valid_token(client, db, token, detail):
    r = refresh(client, token=token)
    assert r.status_code == 401 and r.json()["detail"] == detail
    assert_cookies_cleared(r)


# ── logout ──────────────────────────────────────────────────

def test_logout_revokes_the_session_and_clears_cookies(client, user):
    token = login(client).cookies[security.REFRESH_COOKIE]
    r = client.post(f"{API}/auth/logout", headers=csrf(client))
    assert r.status_code == 204
    assert_cookies_cleared(r)
    assert client.cookies.get(security.ACCESS_COOKIE) is None
    assert refresh(client, token=token).status_code == 401


def test_logout_works_after_the_access_token_expired(client, user):
    token = login(client).cookies[security.REFRESH_COOKIE]
    client.cookies.delete(security.ACCESS_COOKIE)
    assert client.post(f"{API}/auth/logout", headers=csrf(client)).status_code == 204
    assert refresh(client, token=token).status_code == 401


# ── password change ─────────────────────────────────────────

def test_password_change_ends_other_sessions(client, user):
    other_session = login(client).cookies[security.REFRESH_COOKIE]
    login(client)
    r = client.post(f"{API}/auth/password", json=PASSWORD_CHANGE, headers=csrf(client))
    assert r.status_code == 200

    assert refresh(client).status_code == 200                  # this session continues
    assert refresh(client, token=other_session).status_code == 401
    login(client, password=PASSWORD_CHANGE["new_password"])
    assert client.post(f"{API}/auth/login", json={"email": user.email, "password": PASSWORD}).status_code == 401


def test_password_change_needs_the_current_password(client, user):
    r = client.post(f"{API}/auth/password", headers=bearer(user),
                    json={"current_password": "wrong-password", "new_password": "another-good-password"})
    assert r.status_code == 401


# ── deactivation and roles ──────────────────────────────────

def test_deactivation_applies_immediately(client, user, db):
    token = login(client).cookies[security.REFRESH_COOKIE]
    user.is_active = False
    db.commit()
    assert client.get(f"{API}/auth/me").status_code == 403
    assert refresh(client, token=token).status_code == 403
    assert all(t.revoked_at is not None for t in db.scalars(select(RefreshToken)))


@pytest.fixture
def admin_probe(app):
    @app.get(f"{API}/_admin_probe", dependencies=[Depends(require_admin)])
    def probe():
        return {"ok": True}


def test_admin_only_routes(client, admin_probe, user, admin, db):
    assert client.get(f"{API}/_admin_probe", headers=bearer(user)).status_code == 403
    assert client.get(f"{API}/_admin_probe", headers=bearer(admin)).status_code == 200

    # The role is read per request: a demoted admin loses access with the same token
    headers = bearer(admin)
    db.get(User, admin.id).role = "user"
    db.commit()
    assert client.get(f"{API}/_admin_probe", headers=headers).status_code == 403
