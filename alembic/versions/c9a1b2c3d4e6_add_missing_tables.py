"""add agent_metrics agent_versions datasets eval_runs tables

Revision ID: c9a1b2c3d4e6
Revises: c9a1b2c3d4e5
Create Date: 2026-09-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c9a1b2c3d4e6"
down_revision: Union[str, None] = "f9a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # agent_metrics
    op.create_table(
        "agent_metrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), index=True, nullable=False),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), index=True, nullable=False),
        sa.Column("hour", sa.String(13), index=True, nullable=False),
        sa.Column("messages", sa.Integer, default=0),
        sa.Column("tokens", sa.Integer, default=0),
        sa.Column("errors", sa.Integer, default=0),
        sa.Column("avg_response_ms", sa.Integer, default=0),
        sa.Column("tool_calls", sa.Integer, default=0),
    )

    # agent_versions
    op.create_table(
        "agent_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), index=True, nullable=False),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), index=True, nullable=False),
        sa.Column("version", sa.Integer, default=1),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("system_prompt", sa.Text, default=""),
        sa.Column("llm_config", sa.JSON, default=dict),
        sa.Column("tools", sa.JSON, default=list),
        sa.Column("memory_config", sa.JSON, default=dict),
        sa.Column("governance_config", sa.JSON, default=dict),
        sa.Column("agent_type", sa.String(50), default="custom"),
        sa.Column("change_note", sa.Text, default=""),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # datasets
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), index=True, nullable=False),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), index=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("cases", sa.JSON, default=list),
        sa.Column("extra_data", sa.JSON, default=dict),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # eval_runs
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), index=True, nullable=False),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), index=True, nullable=False),
        sa.Column("dataset_id", sa.String(36), sa.ForeignKey("datasets.id"), nullable=True),
        sa.Column("version_id", sa.String(36), sa.ForeignKey("agent_versions.id"), nullable=True),
        sa.Column("judge_model", sa.String(100), default="openai/gpt-4o-mini"),
        sa.Column("avg_score", sa.Float, default=0.0),
        sa.Column("results", sa.JSON, default=list),
        sa.Column("extra_data", sa.JSON, default=dict),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("eval_runs")
    op.drop_table("datasets")
    op.drop_table("agent_versions")
    op.drop_table("agent_metrics")