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


def _existing_columns(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    # 9051a2b3c4d9 already created these two columns in the initial create_table,
    # so the unguarded add_column aborted the entire chain with "duplicate column
    # name: on_failure" at revision 15 of 30. The schema only ever existed because
    # init_db() runs create_all(); everything after this revision -- including
    # whatsapp_contacts, the LGPD opt-out store, plus sales_funnels, budgets and
    # blacklist -- was never created. Guard each column independently.
    present = _existing_columns("workflow_nodes")
    if not present:
        return
    with op.batch_alter_table("workflow_nodes", schema=None) as batch_op:
        if "on_failure" not in present:
            batch_op.add_column(sa.Column("on_failure", sa.String(length=20), nullable=False, server_default="fail"))
        if "retry_count" not in present:
            batch_op.add_column(sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    present = _existing_columns("workflow_nodes")
    with op.batch_alter_table("workflow_nodes", schema=None) as batch_op:
        if "retry_count" in present:
            batch_op.drop_column("retry_count")
        if "on_failure" in present:
            batch_op.drop_column("on_failure")
