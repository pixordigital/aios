"""create workflows and workflow_nodes tables

Revision ID: 9051a2b3c4d9
Revises: 9051a2b3c4d8
Create Date: 2026-09-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9051a2b3c4d9"
down_revision: Union[str, None] = "9051a2b3c4d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, default=""),
        sa.Column("entry_node_id", sa.String(36), nullable=True),
        sa.Column("timeout_seconds", sa.Integer, default=120),
        sa.Column("status", sa.String(20), default="draft"),
        sa.Column("extra_data", sa.JSON, default=dict),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), index=True, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "workflow_nodes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), sa.ForeignKey("workflows.id"), index=True, nullable=False),
        sa.Column("label", sa.String(255), default=""),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("tool_name", sa.String(255), nullable=True),
        sa.Column("tool_args", sa.JSON, default=dict),
        sa.Column("depends_on", sa.JSON, default=list),
        sa.Column("condition", sa.Text, nullable=True),
        sa.Column("output_key", sa.String(100), default="result"),
        sa.Column("timeout_seconds", sa.Integer, default=60),
        sa.Column("position", sa.JSON, default=dict),
        sa.Column("on_failure", sa.String(20), default="fail"),
        sa.Column("retry_count", sa.Integer, default=0),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), sa.ForeignKey("workflows.id"), index=True, nullable=False),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), index=True, nullable=False),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("status", sa.String(20), default="pending"),
        sa.Column("inputs", sa.JSON, default=dict),
        sa.Column("outputs", sa.JSON, default=dict),
        sa.Column("node_status", sa.JSON, default=dict),
        sa.Column("error", sa.Text, default=""),
        sa.Column("tokens", sa.Integer, default=0),
        sa.Column("cost_usd", sa.Float, default=0.0),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("workflow_nodes")
    op.drop_table("workflows")
