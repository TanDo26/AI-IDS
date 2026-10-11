"""initial schema: users, refresh_tokens, model_versions, uploads, prediction_summaries, audit_log

Revision ID: 0001
Revises:
Create Date: 2026-10-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _created_at(name="created_at"):
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), server_default="user", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _created_at(),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('user', 'admin')", name=op.f("ck_users_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", BIG_ID, nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("details", JSON, nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], name=op.f("fk_audit_log_actor_id_users"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(op.f("ix_audit_log_action"), "audit_log", ["action"])
    op.create_index(op.f("ix_audit_log_created_at"), "audit_log", ["created_at"])

    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bundle_id", sa.String(length=128), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="available", nullable=False),
        sa.Column("manifest", JSON, nullable=False),
        _created_at("registered_at"),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by", sa.Integer(), nullable=True),
        sa.Column("invalid_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('available', 'active', 'invalid', 'retired')",
                           name=op.f("ck_model_versions_status")),
        sa.ForeignKeyConstraint(["activated_by"], ["users.id"], name=op.f("fk_model_versions_activated_by_users"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_versions")),
        sa.UniqueConstraint("bundle_id", name=op.f("uq_model_versions_bundle_id")),
    )
    # At most one active bundle
    op.create_index("uq_model_versions_one_active", "model_versions", ["status"], unique=True,
                    postgresql_where=sa.text("status = 'active'"), sqlite_where=sa.text("status = 'active'"))

    op.create_table(
        "refresh_tokens",
        sa.Column("id", BIG_ID, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_refresh_tokens_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"])
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"])

    op.create_table(
        "uploads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_path", sa.String(length=1024), nullable=False),
        sa.Column("file_type", sa.String(length=8), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("progress", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("n_flows", sa.BigInteger(), nullable=True),
        sa.Column("model_version_id", sa.Integer(), nullable=True),
        _created_at(),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_ms", sa.BigInteger(), nullable=True),
        sa.Column("raw_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("file_type IN ('csv', 'pcap', 'pcapng')", name=op.f("ck_uploads_file_type")),
        sa.CheckConstraint("status IN ('queued', 'converting', 'predicting', 'completed', 'failed')",
                           name=op.f("ck_uploads_status")),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name=op.f("ck_uploads_progress")),
        sa.ForeignKeyConstraint(["model_version_id"], ["model_versions.id"],
                                name=op.f("fk_uploads_model_version_id_model_versions"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_uploads_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uploads")),
    )
    op.create_index(op.f("ix_uploads_status"), "uploads", ["status"])
    op.create_index("ix_uploads_user_id_created_at", "uploads", ["user_id", "created_at"])

    op.create_table(
        "prediction_summaries",
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("n_benign", sa.BigInteger(), nullable=False),
        sa.Column("n_known_attack", sa.BigInteger(), nullable=False),
        sa.Column("n_unknown", sa.BigInteger(), nullable=False),
        sa.Column("attack_breakdown", JSON, nullable=False),
        sa.Column("label_agreement", sa.Float(), nullable=True),
        sa.Column("inference_ms", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["upload_id"], ["uploads.id"], name=op.f("fk_prediction_summaries_upload_id_uploads"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("upload_id", name=op.f("pk_prediction_summaries")),
    )


def downgrade() -> None:
    op.drop_table("prediction_summaries")
    op.drop_index("ix_uploads_user_id_created_at", table_name="uploads")
    op.drop_index(op.f("ix_uploads_status"), table_name="uploads")
    op.drop_table("uploads")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("uq_model_versions_one_active", table_name="model_versions")
    op.drop_table("model_versions")
    op.drop_index(op.f("ix_audit_log_created_at"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_action"), table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("users")
