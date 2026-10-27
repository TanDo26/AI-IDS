"""
ORM tables. Postgres in production; types fall back so tests can use SQLite.

Per-flow results are not stored here: one upload can hold millions of flows, so they go
to Parquet under the results directory and only a summary row lands in Postgres.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON, BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer,
    MetaData, SmallInteger, String, Text, Uuid, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Stable constraint names, so Alembic migrations can refer to them
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

JSONType = JSON().with_variant(JSONB(), "postgresql")
BigId = BigInteger().with_variant(Integer(), "sqlite")  # SQLite only auto-increments INTEGER keys

ROLES = ("user", "admin")
FILE_TYPES = ("csv", "pcap", "pcapng")
UPLOAD_STATUSES = ("queued", "converting", "predicting", "completed", "failed")
MODEL_STATUSES = ("available", "active", "invalid", "retired")


def _in(column, values):
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _now():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_in("role", ROLES), name="role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)        # stored lower-cased
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user", server_default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = _now()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    uploads: Mapped[list["Upload"]] = relationship(back_populates="user")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)     # rotation chain; reuse revokes it
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)   # SHA-256 hex, never the token
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    user_agent: Mapped[str | None] = mapped_column(String(512))
    ip: Mapped[str | None] = mapped_column(String(45))                 # fits IPv6


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        CheckConstraint(_in("status", MODEL_STATUSES), name="status"),
        # At most one active bundle, enforced by the database
        Index("uq_model_versions_one_active", "status", unique=True,
              postgresql_where=text("status = 'active'"), sqlite_where=text("status = 'active'")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bundle_id: Mapped[str] = mapped_column(String(128), unique=True)
    path: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(16), default="available", server_default="available")
    manifest: Mapped[dict] = mapped_column(JSONType)
    registered_at: Mapped[datetime] = _now()
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    invalid_reason: Mapped[str | None] = mapped_column(Text)


class Upload(Base):
    __tablename__ = "uploads"
    __table_args__ = (
        CheckConstraint(_in("file_type", FILE_TYPES), name="file_type"),
        CheckConstraint(_in("status", UPLOAD_STATUSES), name="status"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="progress"),
        Index("ix_uploads_user_id_created_at", "user_id", "created_at"),  # "my uploads" + usage per user
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    original_filename: Mapped[str] = mapped_column(String(255))       # display only, never a path
    stored_path: Mapped[str] = mapped_column(String(1024))
    file_type: Mapped[str] = mapped_column(String(8))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued", index=True)
    progress: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    n_flows: Mapped[int | None] = mapped_column(BigInteger)
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_ms: Mapped[int | None] = mapped_column(BigInteger)
    raw_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # set by retention
    # Deleted by its owner or an admin: files and results are gone, the row stays for usage totals
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="uploads")
    summary: Mapped["PredictionSummary | None"] = relationship(
        back_populates="upload", cascade="all, delete-orphan", passive_deletes=True)


class PredictionSummary(Base):
    __tablename__ = "prediction_summaries"

    upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), primary_key=True)
    n_benign: Mapped[int] = mapped_column(BigInteger)
    n_known_attack: Mapped[int] = mapped_column(BigInteger)
    n_unknown: Mapped[int] = mapped_column(BigInteger)
    attack_breakdown: Mapped[dict] = mapped_column(JSONType)          # {"DDoS": 42, "Portscan": 15, ...}
    label_agreement: Mapped[float | None] = mapped_column(Float)      # when the CSV had a Label column
    inference_ms: Mapped[float] = mapped_column(Float)
    # pcap / pcapng only: packets read, flows extracted, what was left out (src/api/uploads/processing.py)
    capture: Mapped[dict | None] = mapped_column(JSONType)

    upload: Mapped[Upload] = relationship(back_populates="summary")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigId, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), index=True)       # e.g. model.activate, user.deactivate
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
