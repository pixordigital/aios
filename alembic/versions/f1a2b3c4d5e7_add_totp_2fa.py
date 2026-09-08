"""add totp_secret and totp_enabled to users for 2FA

Revision ID: f1a2b3c4d5e7
Revises: c9a1b2c3d4e6
Create Date: 2026-09-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f1a2b3c4d5e7"
down_revision: Union[str, None] = "c9a1b2c3d4e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch mode for SQLite compatibility
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("totp_secret", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("totp_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("totp_enabled")
        batch_op.drop_column("totp_secret")
