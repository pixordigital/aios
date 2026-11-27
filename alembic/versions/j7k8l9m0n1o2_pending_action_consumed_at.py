"""pending action consumed_at for approval replay protection

Revision ID: j7k8l9m0n1o2
Revises: i6j7k8l9m0n1
Create Date: 2026-11-27
"""

from alembic import op
import sqlalchemy as sa


revision = "j7k8l9m0n1o2"
down_revision = "i6j7k8l9m0n1"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return any(c["name"] == column for c in sa.inspect(op.get_bind()).get_columns(table))


def upgrade():
    if _has_table("pending_actions") and not _has_column("pending_actions", "consumed_at"):
        op.add_column("pending_actions", sa.Column("consumed_at", sa.DateTime(), nullable=True))


def downgrade():
    if _has_table("pending_actions") and _has_column("pending_actions", "consumed_at"):
        op.drop_column("pending_actions", "consumed_at")
