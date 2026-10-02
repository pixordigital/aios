"""agent_metrics: unique (agent_id, hour) + samples counter

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-10-01

The metric writer did SELECT-then-INSERT with no unique constraint. Two spans
for the same agent/hour both saw "no row" and both inserted, after which every
read raised MultipleResultsFound -- an error the writer swallowed, so telemetry
for that agent/hour was lost permanently and silently. The duplicate rows also
double-counted every dashboard total.

samples backs a correct weighted running mean for avg_response_ms; the writer
used (avg + dur) / 2, which is only the mean at n == 2.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "agent_metrics"
CONSTRAINT = "uq_agent_metrics_agent_hour"


def _columns() -> set:
    insp = sa.inspect(op.get_bind())
    if TABLE not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(TABLE)}


def upgrade() -> None:
    present = _columns()
    if not present:
        return

    if "samples" not in present:
        op.add_column(
            TABLE,
            sa.Column("samples", sa.Integer(), nullable=False, server_default="0"),
        )

    # Collapse any existing duplicates (keep the newest row per agent/hour)
    # before adding the constraint, otherwise creation fails on exactly the
    # databases that have the duplicates.
    op.execute(
        sa.text(
            f"""
            DELETE FROM {TABLE}
            WHERE id NOT IN (
                SELECT id FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY agent_id, hour ORDER BY rowid DESC
                           ) AS rn
                    FROM {TABLE}
                ) ranked
                WHERE ranked.rn = 1
            )
            """
        )
    )

    insp = sa.inspect(op.get_bind())
    names = set()
    try:
        names = {c.get("name") for c in insp.get_unique_constraints(TABLE)}
    except Exception:
        names = set()
    if CONSTRAINT not in names:
        try:
            names = {i.get("name") for i in insp.get_indexes(TABLE)}
        except Exception:
            names = set()
        if CONSTRAINT not in names:
            with op.batch_alter_table(TABLE, schema=None) as batch_op:
                batch_op.create_unique_constraint(CONSTRAINT, ["agent_id", "hour"])


def downgrade() -> None:
    present = _columns()
    if "samples" in present:
        op.drop_column(TABLE, "samples")
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        batch_op.drop_constraint(CONSTRAINT, type_="unique")