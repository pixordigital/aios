"""usage_records: server-side defaults for counter columns

limits.py writes usage rows with raw SQL, which bypasses SQLAlchemy's
Python-side defaults. Every NOT NULL column without a server_default made the
insert fail (`NOT NULL constraint failed: usage_records.whatsapp_messages`,
then `.whatsapp_split`, ...).

The model now declares server_default for these columns; this migration brings
existing tables in line so raw and ORM inserts behave the same.
"""

revision = "v2w3x4y5z6a7"
down_revision = "u1q2r3s4t5u6"

from alembic import op
import sqlalchemy as sa

TABLE = "usage_records"

# column -> server default
DEFAULTS = {
    "messages": "0",
    "llm_tokens": "0",
    "llm_calls": "0",
    "cost_usd": "0",
    "whatsapp_messages": "0",
    "whatsapp_cost_usd": "0",
    "whatsapp_split": "'{}'",
}


def _existing_columns(conn):
    return {c["name"] for c in sa.inspect(conn).get_columns(TABLE)}


def _columns_needing_default(conn, cols):
    """Which of `cols` currently have no server default."""
    out = []
    for c in sa.inspect(conn).get_columns(TABLE):
        if c["name"] in cols and c.get("default") is None:
            out.append(c["name"])
    return out


def upgrade():
    conn = op.get_bind()
    if not sa.inspect(conn).has_table(TABLE):
        return
    have = _existing_columns(conn)
    todo = {k: v for k, v in DEFAULTS.items() if k in have}
    if not todo:
        return
    with op.batch_alter_table(TABLE) as batch:
        for name, default in todo.items():
            batch.alter_column(
                name,
                server_default=sa.text(default),
                existing_type=None,
            )


def downgrade():
    conn = op.get_bind()
    if not sa.inspect(conn).has_table(TABLE):
        return
    have = _existing_columns(conn)
    todo = [k for k in DEFAULTS if k in have]
    if not todo:
        return
    with op.batch_alter_table(TABLE) as batch:
        for name in todo:
            batch.alter_column(name, server_default=None, existing_type=None)
