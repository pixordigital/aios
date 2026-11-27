"""add per-seat allowed_models to organization memberships

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-11-27
"""

from alembic import op
import sqlalchemy as sa


revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def _has_column(name: str) -> bool:
    cols = sa.inspect(op.get_bind()).get_columns("organization_memberships")
    return any(c["name"] == name for c in cols)


def upgrade():
    if _has_column("allowed_models"):
        return
    with op.batch_alter_table("organization_memberships") as batch_op:
        batch_op.add_column(sa.Column("allowed_models", sa.JSON(), nullable=True))


def downgrade():
    if not _has_column("allowed_models"):
        return
    with op.batch_alter_table("organization_memberships") as batch_op:
        batch_op.drop_column("allowed_models")
