"""add pending_actions, skills tables and artifacts.searchable_content

Revision ID: 9051a2b3c4d7
Revises: 1866e31cbcd8
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9051a2b3c4d7"
down_revision: Union[str, None] = "1866e31cbcd8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), index=True, nullable=False),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), index=True, nullable=False),
        sa.Column("tool_name", sa.String(255), nullable=False),
        sa.Column("tool_args", sa.JSON, nullable=False, server_default="'{}'::json"),
        sa.Column("context_summary", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.String(36), nullable=True),
        sa.Column("decided_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "skills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), index=True, nullable=False),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), index=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("skill_type", sa.String(50), nullable=False, server_default="tool_pattern"),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("input_schema", sa.JSON, nullable=False, server_default="'{}'::json"),
        sa.Column("tags", sa.JSON, nullable=False, server_default="'[]'::json"),
        sa.Column("usage_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("success_rate", sa.Float, nullable=False, server_default="1"),
        sa.Column("source_conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.add_column("artifacts", sa.Column("searchable_content", sa.Text, nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("artifacts", "searchable_content")
    op.drop_table("skills")
    op.drop_table("pending_actions")
