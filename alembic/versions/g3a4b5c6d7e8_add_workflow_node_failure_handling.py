"""add on_failure and retry_count to workflow_nodes

Revision ID: g3a4b5c6d7e8
Revises: f2a3b4c5d6e7
Create Date: 2026-09-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "g3a4b5c6d7e8"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_nodes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("on_failure", sa.String(length=20), nullable=False, server_default="fail"))
        batch_op.add_column(sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("workflow_nodes", schema=None) as batch_op:
        batch_op.drop_column("retry_count")
        batch_op.drop_column("on_failure")
