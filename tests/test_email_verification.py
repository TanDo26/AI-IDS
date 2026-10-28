"""
Email verification (IDS_EMAIL_VERIFICATION): the link sent at sign-up and on request, the app closed
until one is opened, stale unconfirmed accounts released, and delivery (src/api/mail.py).
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select, update

from src.api import mail, ratelimit
from src.api.db.models import AuditLog, EmailToken, Upload, User
from src.api.ratelimit import VERIFY_EMAILS_PER_USER, RateLimiter
from src.api.settings import get_settings
from tests.helpers import API, PASSWORD, csrf, login

CLOSED = "Confirm your email address first"


def signup(client, email="bob@example.com", username="bob"):
    return client.post(f"{API}/auth/signup", json={"email": email, "username": username, "password": PASSWORD})


def link_of(message) -> str:
    return re.search(r"https?://\S+", message.text).group(0)


def token_of(message) -> str:
    return parse_qs(urlsplit(link_of(message)).query)["token"][0]


def verify(client, token):
    return client.post(f"{API}/auth/verify-email", json={"token": token})


def resend(client):
    return client.post(f"{API}/auth/verify-email/resend", headers=csrf(client))


def age(db, user_id, hours=48):
    db.execute(update(User).where(User.id == user_id)
               .values(created_at=datetime.now(timezone.utc) - timedelta(hours=hours)))
    db.commit()


# ── off ─────────────────────────────────────────────────────

def test_off_by_default_nothing_is_sent_and_the_app_is_open(client, db, outbox):
    assert signup(client).status_code == 201
    me = client.get(f"{API}/auth/me").json()
    assert me["email_verified_at"] is None and me["needs_email_verification"] is False
    assert outbox == []
    assert client.get(f"{API}/uploads").status_code == 200
    assert resend(client).status_code == 409


# ── sign-up and the link ────────────────────────────────────

def test_signup_sends_a_link_and_the_app_stays_closed_until_it_is_opened(client, db, verifying):
    r = signup(client)
    assert r.status_code == 201
    assert r.json()["user"]["needs_email_verification"] is True
    [message] = verifying
    assert message.to == "bob@example.com" and "Confirm" in message.subject
    assert link_of(message).startswith("https://testserver/verify-email?token=")
    assert link_of(message) in message.html

    # Signed in, but only the account itself is open
    assert client.get(f"{API}/auth/me").status_code == 200
    for path in ("/uploads", "/uploads/stats"):
        r = client.get(f"{API}{path}")
        assert r.status_code == 403 and r.json()["detail"].startswith(CLOSED), path
    assert client.post(f"{API}/predict", json={}, headers=csrf(client)).status_code == 403

    r = verify(client, token_of(message))
    assert r.status_code == 200 and r.json() == {"email": "bob@example.com"}
    me = client.get(f"{API}/auth/me").json()
    assert me["needs_email_verification"] is False and me["email_verified_at"] is not None
    assert client.get(f"{API}/uploads").status_code == 200


def test_the_link_works_without_a_session_and_twice(client, db, verifying):
    signup(client)
    client.cookies.clear()                   # opened on another device
    token = token_of(verifying[0])
    assert verify(client, token).status_code == 200
    assert verify(client, token).status_code == 200    # opened again: still confirmed
    assert db.scalar(select(User)).email_verified_at is not None


def test_invalid_and_expired_links(client, db, verifying):
    signup(client)
    r = verify(client, "not-a-token")
    assert r.status_code == 400 and "not valid" in r.json()["detail"]
    db.execute(update(EmailToken).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    db.commit()
    r = verify(client, token_of(verifying[0]))
    assert r.status_code == 410 and "expired" in r.json()["detail"]
    assert db.scalar(select(User)).email_verified_at is None


def test_links_point_at_the_public_url(client, db, verifying, override_settings):
    override_settings(public_url="https://ids.example.com/")
    signup(client)
    assert link_of(verifying[0]).startswith("https://ids.example.com/verify-email?token=")


# ── resend ──────────────────────────────────────────────────

def test_resend_replaces_earlier_links(client, db, verifying):
    signup(client)
    r = resend(client)
    assert r.status_code == 202 and r.json() == {"sent_to": "bob@example.com"}
    first, second = verifying
    assert verify(client, token_of(first)).status_code == 400
    assert verify(client, token_of(second)).status_code == 200
    r = resend(client)
    assert r.status_code == 409                      # nothing left to confirm
    assert len(verifying) == 2


def test_resend_needs_a_session(client, db, verifying):
    assert client.post(f"{API}/auth/verify-email/resend").status_code == 401


def test_resend_is_rate_limited(client, db, verifying, override_settings, monkeypatch):
    signup(client)
    override_settings(rate_limits_enabled=True)
    limiter = RateLimiter(None)                         # memory only: no Redis needed
    monkeypatch.setattr(ratelimit, "get_rate_limiter", lambda: limiter)
    allowed = int(VERIFY_EMAILS_PER_USER.split("/")[0])
    assert [resend(client).status_code for _ in range(allowed + 1)] == [202] * allowed + [429]
    assert len(verifying) == 1 + allowed


# ── accounts made elsewhere ─────────────────────────────────

def test_existing_and_admin_made_accounts_count_as_confirmed(client, db, verifying, admin):
    login(client, admin.email)
    assert client.get(f"{API}/admin/users").status_code == 200


def test_admin_pages_need_a_confirmed_address(client, db, verifying, make_user):
    make_user("root@example.com", role="admin", verified=False)
    login(client, "root@example.com")
    r = client.get(f"{API}/admin/users")
    assert r.status_code == 403 and r.json()["detail"].startswith(CLOSED)


def test_admins_see_who_has_not_confirmed(client, db, verifying, admin, make_user):
    make_user("carol@example.com", verified=False)
    login(client, admin.email)
    items = {u["email"]: u for u in client.get(f"{API}/admin/users").json()["items"]}
    assert items["carol@example.com"]["needs_email_verification"] is True
    assert items[admin.email]["needs_email_verification"] is False


# ── stale accounts ──────────────────────────────────────────

@pytest.mark.parametrize("held", ["email", "username"])
def test_a_stale_unconfirmed_account_is_released(client, db, verifying, make_user, held):
    squatter = (make_user("bob@example.com", username="someone", verified=False) if held == "email"
                else make_user("other@example.com", username="bob", verified=False))
    squatter_id, squatter_name = squatter.id, squatter.username
    age(db, squatter_id)
    assert signup(client).status_code == 201
    db.expire_all()   # (SQLite may hand the new account the deleted one's id)
    assert [(u.email, u.username) for u in db.scalars(select(User))] == [("bob@example.com", "bob")]
    log = db.scalar(select(AuditLog).where(AuditLog.action == "user.purge_unverified"))
    assert log.target_id == str(squatter_id) and log.details["username"] == squatter_name


@pytest.mark.parametrize("kind", ["recent", "confirmed", "has uploads", "admin", "verification off"])
def test_other_accounts_keep_their_address(client, db, verifying, make_user, override_settings, kind):
    holder = make_user("bob@example.com", username="someone", verified=kind == "confirmed",
                       role="admin" if kind == "admin" else "user")
    if kind != "recent":
        age(db, holder.id)
    if kind == "has uploads":
        db.add(Upload(user_id=holder.id, original_filename="a.csv", stored_path="x", file_type="csv",
                      size_bytes=1, sha256="0" * 64))
        db.commit()
    if kind == "verification off":
        override_settings(email_verification=False)
    r = signup(client)
    assert r.status_code == 409 and "email" in r.json()["detail"]
    db.expire_all()
    assert db.get(User, holder.id) is not None


# ── settings and delivery ───────────────────────────────────

def test_production_refuses_verification_without_smtp(override_settings):
    override_settings(env="production", email_verification=True)
    with pytest.raises(RuntimeError, match="IDS_EMAIL_VERIFICATION"):
        get_settings()
    override_settings(env="development")
    with pytest.warns(UserWarning, match="IDS_EMAIL_VERIFICATION"):
        get_settings()


class FakeSMTP:
    """Stands in for smtplib.SMTP / SMTP_SSL and records what was done."""
    calls: list = []

    def __init__(self, host, port, timeout=None, context=None):
        FakeSMTP.calls.append(("connect", type(self).__name__, host, port))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        FakeSMTP.calls.append(("quit",))

    def starttls(self, context=None):
        FakeSMTP.calls.append(("starttls",))

    def login(self, user, password):
        FakeSMTP.calls.append(("login", user, password))

    def send_message(self, message):
        FakeSMTP.calls.append(("send", message))


class FakeSMTP_SSL(FakeSMTP):
    pass


@pytest.mark.parametrize("security, username", [("starttls", "apikey"), ("ssl", "apikey"), ("none", "")])
def test_smtp_delivery(monkeypatch, override_settings, security, username):
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSMTP_SSL)
    FakeSMTP.calls = []
    override_settings(mail_backend="smtp", smtp_host="smtp.example.com", smtp_port=2525, smtp_security=security,
                      smtp_username=username, smtp_password="s3cret", mail_from="AI-IDS <no-reply@example.com>")
    mail.send(mail.Message("bob@example.com", "Hello", "plain body", "<p>html body</p>"))

    names = [c[0] for c in FakeSMTP.calls]
    assert FakeSMTP.calls[0] == ("connect", "FakeSMTP_SSL" if security == "ssl" else "FakeSMTP",
                                 "smtp.example.com", 2525)
    assert ("starttls" in names) == (security == "starttls")
    assert (("login", "apikey", "s3cret") in FakeSMTP.calls) == bool(username)
    sent = FakeSMTP.calls[names.index("send")][1]
    assert sent["To"] == "bob@example.com" and sent["Subject"] == "Hello"
    assert sent["From"] == "AI-IDS <no-reply@example.com>" and sent["Message-ID"].endswith("@example.com>")
    assert sent.get_body(("plain",)).get_content().strip() == "plain body"
    assert "html body" in sent.get_body(("html",)).get_content()
    assert names[-1] == "quit"


def test_console_backend_logs_the_message(caplog):
    with caplog.at_level(logging.INFO, logger="ids.mail"):
        mail.send(mail.Message("bob@example.com", "Hello", "the link: https://x/verify-email?token=t", "<p>x</p>"))
    [record] = [r for r in caplog.records if r.name == "ids.mail"]
    assert "not sent" in record.getMessage() and record.to == "bob@example.com"
    assert "token=t" in record.body


def test_a_failed_delivery_is_logged_and_signup_still_works(client, db, verifying, monkeypatch, caplog):
    def broken(message):
        raise OSError("connection refused")
    monkeypatch.setattr(mail, "send", broken)
    with caplog.at_level(logging.ERROR, logger="ids.mail"):
        assert signup(client).status_code == 201
    assert any(r.name == "ids.mail" and "Could not send" in r.getMessage() for r in caplog.records)
