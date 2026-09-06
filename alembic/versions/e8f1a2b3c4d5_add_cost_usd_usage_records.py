"""add cost_usd to usage_records

Revision ID: e8f1a2b3c4d5
Revises: d4e5f6a7b8c9
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "e8f1a2b3c4d5"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("usage_records", sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"))

def downgrade() -> None:
    op.drop_column("usage_records", "cost_usd")
