"""usage_records: unique (org_id, date)

check_org_limits() and track_usage() both do an atomic upsert with
ON CONFLICT (org_id, date). The table only had separate indexes on org_id and
date, so no unique constraint ever matched and both functions raised on every
call (masked in production only because internal_mode returns early).

Duplicate rows are collapsed first, keeping the most recent per (org_id, date).
"""

revision = "u1q2r3s4t5u6"
down_revision = "s4l3sg0a1s01"

from alembic import op
import sqlalchemy as sa

TABLE = "usage_records"
CONSTRAINT = "uq_usage_records_org_date"


def _has_constraint(conn, name: str) -> bool:
    insp = sa.inspect(conn)
    for uc in insp.get_unique_constraints(TABLE):
        if uc.get("name") == name:
            return True
    for idx in insp.get_indexes(TABLE):
        if idx.get("name") == name:
            return True
    return False


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if not insp.has_table(TABLE) or _has_constraint(conn, CONSTRAINT):
        return

    # Collapse duplicates: keep the newest row per (org_id, date).
    op.execute(
        sa.text(
            f"""
            DELETE FROM {TABLE}
            WHERE id NOT IN (
                SELECT id FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY org_id, date ORDER BY id DESC
                           ) AS rn
                    FROM {TABLE}
                ) ranked
                WHERE ranked.rn = 1
            )
            """
        )
    )

    with op.batch_alter_table(TABLE) as batch:
        batch.create_unique_constraint(CONSTRAINT, ["org_id", "date"])


def downgrade():
    conn = op.get_bind()
    if _has_constraint(conn, CONSTRAINT):
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_constraint(CONSTRAINT, type_="unique")
