"""conversations: one thread per (org, channel, connection, contact)

`process_inbound` resolved the thread by "latest conversation on this channel".
A channel is a phone number, so every customer of that number shared a single
conversation: their messages interleaved with each other's, the agent's memory
and RAG injections mixed them, and the inbox showed one row for the whole
business. The lookup is now keyed on `external_id` (the contact), and this
constraint is what makes it safe under concurrency — two workers handling the
same contact's first message at once must not both create the thread.

Existing rows are left alone. They have `external_id` set only if the caller
supplied one, and the new code tolerates a NULL there, so no backfill is needed
to make this deployable.

Idempotent, and safe on a database where the constraint already exists.
"""

revision = "n3o4p5q6r7s8"
down_revision = "m2n3o4p5q6r7"

import sqlalchemy as sa

from alembic import op

TABLE = "conversations"
NAME = "uq_conversations_org_channel_contact"


def _exists(bind) -> bool:
    insp = sa.inspect(bind)
    if TABLE not in insp.get_table_names():
        return False
    return any(c.get("name") == NAME for c in insp.get_unique_constraints(TABLE))


def upgrade():
    bind = op.get_bind()
    if _exists(bind):
        return
    # A unique index rather than a table constraint: on a table that already
    # holds duplicate rows this would fail as a constraint creation, while
    # CREATE UNIQUE INDEX ... IF NOT EXISTS is a no-op we can reason about.
    # The duplicate rows are the bug being fixed, not something to refuse over.
    op.create_index(
        NAME,
        TABLE,
        ["org_id", "channel", "channel_connection_id", "external_id"],
        unique=True,
        if_not_exists=True,
    )


def downgrade():
    bind = op.get_bind()
    if not _exists(bind):
        return
    op.drop_index(NAME, table_name=TABLE)
