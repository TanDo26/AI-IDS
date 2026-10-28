"""email verification: users.email_verified_at and the email_tokens table

Accounts that exist already count as verified: they were made before addresses were checked, and
switching IDS_EMAIL_VERIFICATION on must not lock them out.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET email_verified_at = created_at")

    op.create_table(
        "email_tokens",
        sa.Column("id", BIG_ID, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("purpose IN ('verify')", name=op.f("ck_email_tokens_purpose")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_email_tokens_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_email_tokens_token_hash")),
    )
    op.create_index(op.f("ix_email_tokens_user_id"), "email_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_email_tokens_user_id"), table_name="email_tokens")
    op.drop_table("email_tokens")
    with op.batch_alter_table("users") as batch:   # SQLite rebuilds the table
        batch.drop_column("email_verified_at")
