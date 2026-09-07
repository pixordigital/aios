"""automations, knowledge, handover + channel encryption

Revision ID: c9a1b2c3d4e5
Revises: b3c4d5e6f7a8
Create Date: 2026-09-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "c9a1b2c3d4e5"
down_revision: Union[str, None] = "9051a2b3c4d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table("automation_triggers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), sa.ForeignKey("workflows.id"), nullable=False, index=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("type", sa.String(30), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("config", sa.JSON, nullable=False, server_default="'{}'::json"),
        sa.Column("webhook_path", sa.String(255), nullable=True, unique=True, index=True),
        sa.Column("cron_expr", sa.String(100), nullable=True),
        sa.Column("event_type", sa.String(100), nullable=True),
        sa.Column("last_run_at", sa.DateTime, nullable=True),
        sa.Column("next_run_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table("credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("cred_type", sa.String(50), nullable=False),
        sa.Column("data_enc", sa.Text, nullable=False, server_default=""),
        sa.Column("extra_data", sa.JSON, nullable=False, server_default="'{}'::json"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table("workflow_execution_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("workflow_runs.id"), nullable=False, index=True),
        sa.Column("workflow_id", sa.String(36), sa.ForeignKey("workflows.id"), nullable=False, index=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("node_id", sa.String(36), nullable=True),
        sa.Column("level", sa.String(20), nullable=False, server_default="info"),
        sa.Column("message", sa.Text, nullable=False, server_default=""),
        sa.Column("data", sa.JSON, nullable=False, server_default="'{}'::json"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

def downgrade() -> None:
    op.drop_table("workflow_execution_logs")
    op.drop_table("credentials")
    op.drop_table("automation_triggers")
