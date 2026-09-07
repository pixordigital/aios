"""add tokens/cost_usd to workflow_runs (automations 500 fix)

Revision ID: f9a2b3c4d5e6
Revises: e8f1a2b3c4d5
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "f9a2b3c4d5e6"
down_revision: Union[str, None] = "e8f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("workflow_runs", sa.Column("tokens", sa.Integer, nullable=False, server_default="0"))
    op.add_column("workflow_runs", sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"))

def downgrade() -> None:
    op.drop_column("workflow_runs", "cost_usd")
    op.drop_column("workflow_runs", "tokens")
