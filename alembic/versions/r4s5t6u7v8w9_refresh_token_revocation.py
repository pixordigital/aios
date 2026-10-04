"""refresh token revocation

Revision ID: r4s5t6u7v8w9
Revises: f7a8b9c0d1e2
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "r4s5t6u7v8w9"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Created with sa.inspect rather than a raw information_schema query: that
    # dialect-specific query was the thing that broke SQLite in a past migration.
    inspector = sa.inspect(op.get_bind())
    if "refresh_tokens" in inspector.get_table_names():
        return
    op.create_table(
        "refresh_tokens",
        sa.Column("jti", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("replaced_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])
    op.create_index("ix_refresh_tokens_created_at", "refresh_tokens", ["created_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "refresh_tokens" not in inspector.get_table_names():
        return
    op.drop_table("refresh_tokens")
