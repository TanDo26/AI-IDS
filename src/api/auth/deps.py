"""
FastAPI dependencies: who is calling, and are they allowed.
"""

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.api.auth import security
from src.api.db.models import User
from src.api.db.session import get_db
from src.api.settings import get_settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def require_csrf(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    if not security.tokens_match(request.headers.get(security.CSRF_HEADER),
                                 request.cookies.get(security.CSRF_COOKIE)):
        raise HTTPException(status_code=403, detail="Missing or invalid CSRF token")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
    else:
        token = request.cookies.get(security.ACCESS_COOKIE)
        if token:
            require_csrf(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})

    try:
        user_id = security.decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Access token expired", headers={"WWW-Authenticate": "Bearer"})
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid access token", headers={"WWW-Authenticate": "Bearer"})

    # Role and status come from the database, so a demotion or deactivation applies at once
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid access token", headers={"WWW-Authenticate": "Bearer"})
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")
    request.state.user_id = user.id         # for the access log (src/api/main.py)
    return user


def get_verified_user(user: User = Depends(get_current_user)) -> User:
    """get_current_user, whose email address is confirmed when IDS_EMAIL_VERIFICATION is on."""
    if get_settings().email_verification and user.email_verified_at is None:
        raise HTTPException(status_code=403, detail="Confirm your email address first: open the link we sent you")
    return user


def require_admin(user: User = Depends(get_verified_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user
