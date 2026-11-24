"""Durable org-scoped ICM side-effect idempotency claims.

ICM side effects used to be deduped only in run outputs / in-memory state, so
they duplicated across runs and process restarts. One row per (org, key) is the
durable audit boundary.
"""

revision = "f0e1d2c3b4a5"
down_revision = "d0e1f2a3b4c5"

from alembic import op
import sqlalchemy as sa

TABLE = "icm_side_effects"
UQ = "uq_icm_side_effects_org_key"


def upgrade():
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if TABLE in have:
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("stage_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("run_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("org_id", "idempotency_key", name=UQ),
    )
    op.create_index("ix_icm_side_effects_org_id", TABLE, ["org_id"])
    op.create_index("ix_icm_side_effects_created_at", TABLE, ["created_at"])


def downgrade():
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if TABLE in have:
        op.drop_table(TABLE)
