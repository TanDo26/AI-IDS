"""
Accounts and sessions.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from src.api.auth import security
from src.api.db.models import RefreshToken, User
from src.api.settings import get_settings


class AuthError(Exception):
    """Maps to an HTTP error in the router: status + safe message."""

    def __init__(self, status: int, message: str):
        self.status, self.message = status, message
        super().__init__(message)


@dataclass
class IssuedTokens:
    user: User
    access_token: str
    refresh_token: str
    csrf_token: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite returns naive datetimes


def signup(db: Session, email: str, username: str, password: str) -> User:
    existing = db.scalar(select(User).where(or_(User.email == email, User.username == username)))
    if existing is not None:
        field = "email" if existing.email == email else "username"
        raise AuthError(409, f"That {field} is already registered")
    user = User(email=email, username=username, password_hash=security.hash_password(password), role="user")
    db.add(user)
    db.commit()
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        security.burn_password_check(password)
        raise AuthError(401, "Incorrect email or password")
    if not security.verify_password(password, user.password_hash):
        raise AuthError(401, "Incorrect email or password")
    if not user.is_active:
        raise AuthError(403, "Account is deactivated")
    user.last_login_at = _now()
    db.commit()
    return user


def issue_tokens(db: Session, user: User, family_id: uuid.UUID | None = None,
                 user_agent: str | None = None, ip: str | None = None) -> IssuedTokens:
    """New access token + refresh token (in a new family unless one is given) + CSRF token."""
    refresh = security.new_opaque_token()
    db.add(RefreshToken(
        user_id=user.id,
        family_id=family_id or uuid.uuid4(),
        token_hash=security.hash_token(refresh),
        expires_at=_now() + timedelta(days=get_settings().refresh_token_days),
        user_agent=(user_agent or "")[:512] or None,
        ip=ip,
    ))
    db.commit()
    return IssuedTokens(user, security.create_access_token(user.id), refresh, security.new_opaque_token())


def _revoke_family(db: Session, family_id: uuid.UUID) -> None:
    db.execute(update(RefreshToken)
               .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=_now()))


def rotate_refresh_token(db: Session, raw_token: str | None,
                         user_agent: str | None = None, ip: str | None = None) -> IssuedTokens:
    if not raw_token:
        raise AuthError(401, "Not logged in")
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == security.hash_token(raw_token)))
    if token is None:
        raise AuthError(401, "Session not found")
    if token.revoked_at is not None:
        _revoke_family(db, token.family_id)  # replayed token: end the whole session
        db.commit()
        raise AuthError(401, "Session ended; please log in again")
    if _aware(token.expires_at) <= _now():
        raise AuthError(401, "Session expired; please log in again")

    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        _revoke_family(db, token.family_id)
        db.commit()
        raise AuthError(403, "Account is deactivated")

    token.revoked_at = _now()
    return issue_tokens(db, user, token.family_id, user_agent, ip)


def logout(db: Session, raw_token: str | None) -> None:
    if not raw_token:
        return
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == security.hash_token(raw_token)))
    if token is not None:
        _revoke_family(db, token.family_id)
        db.commit()


def change_password(db: Session, user: User, current: str, new: str,
                    user_agent: str | None = None, ip: str | None = None) -> IssuedTokens:
    if not security.verify_password(current, user.password_hash):
        raise AuthError(401, "Current password is incorrect")
    user.password_hash = security.hash_password(new)
    # Every other session ends; this one continues with fresh tokens
    db.execute(update(RefreshToken)
               .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=_now()))
    db.commit()
    return issue_tokens(db, user, user_agent=user_agent, ip=ip)
