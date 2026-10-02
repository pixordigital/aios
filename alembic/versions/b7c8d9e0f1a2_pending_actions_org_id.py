"""pending_actions: add org_id so the approval queue is tenant-scoped

Revision ID: b7c8d9e0f1a2
Revises: z6a7b8c9d0e1
Create Date: 2026-10-01

Why: PendingAction had no org_id, so `GET /api/approvals` filtered only on
status and returned other tenants' tool_args and context_summary, and
approve/reject mutated another tenant's row (reporting 404 while the write
still landed via the fire-and-forget DB fallback). The dashboard queries that
filtered on PendingAction.org_id could not run at all -- the attribute did not
exist, so building the query raised AttributeError and the CRM page,
control_center and handover routes 500'd.

Backfill joins through agents.org_id, because every PendingAction references an
agent. Rows whose agent is missing keep an empty org_id and are invisible to
every org-scoped query rather than being exposed to one -- fail closed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "z6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "pending_actions"


def _columns() -> set:
    inspector = sa.inspect(op.get_bind())
    if TABLE not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(TABLE)}


def upgrade() -> None:
    present = _columns()
    if not present:
        return
    if "org_id" not in present:
        # server_default so this succeeds on a populated table, then backfill,
        # then drop the default so new writes must supply a real org.
        op.add_column(
            TABLE,
            sa.Column("org_id", sa.String(length=36), nullable=False, server_default=""),
        )
        op.execute(
            sa.text(
                f"UPDATE {TABLE} SET org_id = ("
                f"  SELECT a.org_id FROM agents a WHERE a.id = {TABLE}.agent_id"
                f") WHERE org_id = ''"
            )
        )
        # SQLite cannot ALTER COLUMN at all; env.py sets render_as_batch for it.
        # Without the batch wrapper this migration aborted on SQLite right after
        # adding the column.
        with op.batch_alter_table(TABLE, schema=None) as batch_op:
            batch_op.alter_column(
                "org_id", existing_type=sa.String(length=36), server_default=None
            )
    op.create_index(
        "ix_pending_actions_org_id_status",
        TABLE,
        ["org_id", "status"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    present = _columns()
    op.drop_index("ix_pending_actions_org_id_status", table_name=TABLE)
    if "org_id" in present:
        op.drop_column(TABLE, "org_id")