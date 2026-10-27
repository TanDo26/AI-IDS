"""prediction_summaries.capture: what the flow extractor read from an uploaded pcap / pcapng

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column("prediction_summaries", sa.Column("capture", JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("prediction_summaries") as batch:   # SQLite rebuilds the table
        batch.drop_column("capture")
