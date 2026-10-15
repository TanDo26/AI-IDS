"""
Password hashing, access tokens (JWT) and opaque refresh / CSRF tokens.
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from src.api.settings import get_settings

BCRYPT_ROUNDS = 12
PASSWORD_MIN_BYTES = 8
PASSWORD_MAX_BYTES = 72          # bcrypt uses (and bcrypt>=5 accepts) at most 72 bytes
JWT_ALGORITHM = "HS256"

ACCESS_COOKIE = "ids_access"
REFRESH_COOKIE = "ids_refresh"
CSRF_COOKIE = "ids_csrf"
CSRF_HEADER = "X-CSRF-Token"


def validate_password(password: str) -> None:
    size = len(password.encode("utf-8"))
    if not PASSWORD_MIN_BYTES <= size <= PASSWORD_MAX_BYTES:
        raise ValueError(f"Password must be {PASSWORD_MIN_BYTES}-{PASSWORD_MAX_BYTES} bytes (UTF-8)")


def hash_password(password: str) -> str:
    validate_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:  # over 72 bytes, or a malformed hash
        return False


# Checked when the email is unknown, so a failed login takes the same time either way
_DUMMY_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")


def burn_password_check(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def create_access_token(user_id: int, minutes: int | None = None) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    lifetime = timedelta(minutes=settings.access_token_minutes if minutes is None else minutes)
    payload = {"sub": str(user_id), "type": "access", "iat": now, "exp": now + lifetime,
               "jti": uuid.uuid4().hex}
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> int:
    """User id from a valid, unexpired access token; raises jwt.InvalidTokenError otherwise."""
    payload = jwt.decode(token, get_settings().secret_key.get_secret_value(), algorithms=[JWT_ALGORITHM],
                         options={"require": ["exp", "sub", "type"]})
    if payload["type"] != "access":
        raise jwt.InvalidTokenError("not an access token")
    return int(payload["sub"])


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Refresh tokens are stored as SHA-256 only: a database leak doesn't hand out sessions."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(a, b)
