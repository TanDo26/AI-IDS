"""
Request / response models for /auth.
"""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.api.auth.security import validate_password

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_USERNAME = re.compile(r"[A-Za-z0-9_.-]{3,64}")


def normalize_email(email: str) -> str:
    return email.strip().lower()


class SignupRequest(BaseModel):
    email: str = Field(max_length=320)
    username: str
    password: str

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        v = normalize_email(v)
        if not _EMAIL.fullmatch(v):
            raise ValueError("Not a valid email address")
        return v

    @field_validator("username")
    @classmethod
    def _username(cls, v):
        v = v.strip()
        if not _USERNAME.fullmatch(v):
            raise ValueError("Username: 3-64 characters, letters, digits, '_', '.', '-'")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v):
        validate_password(v)
        return v


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        return normalize_email(v)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password(cls, v):
        validate_password(v)
        return v


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    username: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class TokenResponse(BaseModel):
    """The access token is also set as an httpOnly cookie; scripts use it as a Bearer token."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int          # seconds
    user: UserOut
