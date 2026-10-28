"""
Email verification (IDS_EMAIL_VERIFICATION): a new account gets a one-time link by email, and until
it is opened the account can sign in but not use the app (deps.get_verified_user).

- Links hold an opaque token; only its SHA-256 is stored (email_tokens). A new link replaces the
  user's unused ones, and a link works for IDS_EMAIL_TOKEN_HOURS.
- Opening a link a second time still says the address is confirmed.
- Links point at IDS_PUBLIC_URL, or at the address the request came in on when it is empty.
- An address or username held by an account that never confirmed within a link's lifetime, and has
  no uploads, is released when someone signs up with it, so nobody can block an address by
  registering it first.
"""

import html
from datetime import timedelta
from urllib.parse import quote

from fastapi import Request
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from src.api.auth import security
from src.api.auth.service import AuthError, _aware, _now
from src.api.db.models import AuditLog, EmailToken, Upload, User
from src.api.mail import Message
from src.api.settings import get_settings

VERIFY = "verify"


def required(user: User) -> bool:
    """Does this user still have to confirm their address?"""
    return get_settings().email_verification and user.email_verified_at is None


def base_url(request: Request) -> str:
    return get_settings().public_url.rstrip("/") or str(request.base_url).rstrip("/")


def new_link(db: Session, user: User, base: str) -> str:
    """A fresh verification link; the user's unused ones stop working. The caller commits."""
    db.execute(delete(EmailToken).where(EmailToken.user_id == user.id, EmailToken.purpose == VERIFY,
                                        EmailToken.used_at.is_(None)))
    raw = security.new_opaque_token()
    db.add(EmailToken(user_id=user.id, purpose=VERIFY, token_hash=security.hash_token(raw),
                      expires_at=_now() + timedelta(hours=get_settings().email_token_hours)))
    return f"{base}/verify-email?token={quote(raw)}"


def message(user: User, link: str) -> Message:
    hours = get_settings().email_token_hours
    name = html.escape(user.username)
    return Message(
        to=user.email,
        subject="Confirm your email address for AI-IDS",
        text=(f"Hello {user.username},\n\n"
              f"Open this link to confirm your email address and start using AI-IDS:\n\n{link}\n\n"
              f"The link works for {hours} hours. If you didn't create an account, ignore this email.\n"),
        html=(f"<p>Hello {name},</p>"
              f"<p>Confirm your email address to start using AI-IDS:</p>"
              f'<p><a href="{html.escape(link)}" style="display:inline-block;padding:10px 16px;'
              f'background:#1d4ed8;color:#ffffff;border-radius:6px;text-decoration:none">'
              f"Confirm my email address</a></p>"
              f'<p>Or copy this link into your browser:<br><a href="{html.escape(link)}">{html.escape(link)}</a></p>'
              f"<p>The link works for {hours} hours. If you didn't create an account, ignore this email.</p>"),
    )


def verify(db: Session, raw_token: str) -> User:
    token = db.scalar(select(EmailToken).where(EmailToken.token_hash == security.hash_token(raw_token),
                                               EmailToken.purpose == VERIFY))
    user = db.get(User, token.user_id) if token is not None else None
    if user is None:
        raise AuthError(400, "This link is not valid. Sign in to get a new one.")
    if token.used_at is not None:
        if user.email_verified_at is not None:
            return user                      # opened twice
        raise AuthError(400, "This link is not valid. Sign in to get a new one.")
    if _aware(token.expires_at) <= _now():
        raise AuthError(410, "This link has expired. Sign in to get a new one.")
    token.used_at = _now()
    if user.email_verified_at is None:
        user.email_verified_at = token.used_at
    db.commit()
    return user


def release_stale(db: Session, email: str, username: str) -> None:
    """Delete never-confirmed accounts that hold this email or username (see the module docstring).
    The caller commits."""
    cutoff = _now() - timedelta(hours=get_settings().email_token_hours)
    stale = db.scalars(select(User).where(
        or_(User.email == email, User.username == username),
        User.email_verified_at.is_(None), User.role == "user", User.created_at < cutoff,
        ~select(Upload.id).where(Upload.user_id == User.id).exists(),
    )).all()
    for user in stale:
        db.add(AuditLog(actor_id=None, action="user.purge_unverified", target_type="user", target_id=str(user.id),
                        details={"email": user.email, "username": user.username}))
    if stale:
        db.execute(delete(User).where(User.id.in_([u.id for u in stale])))
        db.flush()
