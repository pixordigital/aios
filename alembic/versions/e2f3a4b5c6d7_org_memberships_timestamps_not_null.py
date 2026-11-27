"""backfill org membership timestamps then enforce NOT NULL

Revision ID: e2f3a4b5c6d7
Revises: c1d2e3f4a5b6
Create Date: 2026-11-26
"""

from alembic import op
import sqlalchemy as sa


revision = "e2f3a4b5c6d7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _org_memberships_columns() -> dict[str, dict]:
    if not _has_table("organization_memberships"):
        return {}
    return {c["name"]: c for c in sa.inspect(op.get_bind()).get_columns("organization_memberships")}


def upgrade():
    cols = _org_memberships_columns()
    if not cols:
        return

    bind = op.get_bind()

    # Backfill NULLs (ad-hoc rows) before enforcing NOT NULL, matching TimestampMixin intent.
    # CURRENT_TIMESTAMP must stay inline: bound sa.func.now() reaches asyncpg as a
    # SQL expression object and raises DataError on Postgres.
    if "created_at" in cols:
        bind.execute(sa.text("UPDATE organization_memberships SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
    if "updated_at" in cols:
        bind.execute(sa.text("UPDATE organization_memberships SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))

    # Re-inspect after backfill so we only alter columns still nullable.
    cols = _org_memberships_columns()
    nullable_updates = [
        name
        for name in ("created_at", "updated_at")
        if name in cols and cols[name].get("nullable") is True
    ]
    if nullable_updates:
        with op.batch_alter_table("organization_memberships") as batch_op:
            for name in nullable_updates:
                batch_op.alter_column(name, existing_type=sa.DateTime(), nullable=False)


def downgrade():
    # Best-effort: allow NULLs again (no data loss). Safe no-op if table missing.
    cols = _org_memberships_columns()
    if not cols:
        return
    nullable_drops = [
        name
        for name in ("created_at", "updated_at")
        if name in cols and cols[name].get("nullable") is False
    ]
    if nullable_drops:
        with op.batch_alter_table("organization_memberships") as batch_op:
            for name in nullable_drops:
                batch_op.alter_column(name, existing_type=sa.DateTime(), nullable=True)
