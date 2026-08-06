"""add dead_letters table for retry/DLQ

Revision ID: 9051a2b3c4d8
Revises: 9051a2b3c4d7
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9051a2b3c4d8"
down_revision: Union[str, None] = "9051a2b3c4d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dead_letters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), index=True, nullable=True),
        sa.Column("channel_type", sa.String(50), nullable=False),
        sa.Column("channel_connection_id", sa.String(36), index=True, nullable=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), index=True, nullable=True),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("job_name", sa.String(255), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False, server_default="'{}'::json"),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="failed"),
        sa.Column("retried_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("dead_letters")
