"""crm deals pipeline IA

Revision ID: d4e5f6a7b8c9
Revises: c9a1b2c3d4e5
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c9a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table("crm_deals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("lead_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("lead_email", sa.String(255), nullable=False, server_default="", index=True),
        sa.Column("lead_phone", sa.String(50), nullable=False, server_default=""),
        sa.Column("stage", sa.String(30), nullable=False, server_default="prospection", index=True),
        sa.Column("value", sa.Float, nullable=False, server_default="0"),
        sa.Column("currency", sa.String(10), nullable=False, server_default="BRL"),
        sa.Column("score", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("source", sa.String(50), nullable=False, server_default="whatsapp"),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=True, index=True),
        sa.Column("team_id", sa.String(36), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("pipeline", sa.String(50), nullable=False, server_default="default"),
        sa.Column("extra_data", sa.JSON, nullable=False, server_default="'{}'::json"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

def downgrade() -> None:
    op.drop_table("crm_deals")
