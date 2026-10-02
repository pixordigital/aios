"""messages: unique (org_id, channel_message_id) for redelivery dedup

Slack sends event retries and Evolution redelivers; the worker inserted a new
Message row per delivery because nothing identified a provider message.
The send path now populates channel_message_id and pre-checks it; this
constraint is the backstop for races between the check and the insert.

Postgres UNIQUE treats NULLs as distinct, so existing rows with a NULL
channel_message_id are unaffected. Idempotent: skips if already present.
"""

revision = "x4y5z6a7b8c9"
down_revision = "w3x4y5z6a7b8"

from alembic import op
import sqlalchemy as sa

TABLE = "messages"
CONSTRAINT = "uq_messages_org_provider_msg"


def _has_constraint(bind) -> bool:
    insp = sa.inspect(bind)
    if hasattr(insp, "get_unique_constraints"):
        return any(
            u.get("name") == CONSTRAINT
            for u in insp.get_unique_constraints(TABLE)
        )
    # sqlite / older dialects: fall back to index names
    return any(
        i.get("name") == CONSTRAINT for i in insp.get_indexes(TABLE)
    )


def upgrade():
    if not _has_constraint(op.get_bind()):
        # This migration exists precisely because the database already holds
        # duplicates of (org_id, channel_message_id) -- that is why dedup was
        # added. Creating the constraint without collapsing them first fails
        # with "Key (...) is duplicated", i.e. exactly on the databases that
        # need the migration. Collapse first, keeping the newest row per key.
        # NULL channel_message_id rows are untouched (Postgres treats NULLs as
        # distinct in a unique index).
        op.execute(
            sa.text(
                f"""
                DELETE FROM {TABLE}
                WHERE channel_message_id IS NOT NULL
                  AND id NOT IN (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY org_id, channel_message_id
                                   ORDER BY created_at DESC, id DESC
                               ) AS rn
                        FROM {TABLE}
                        WHERE channel_message_id IS NOT NULL
                    ) ranked
                    WHERE ranked.rn = 1
                )
                """
            )
        )
        # batch mode: SQLite cannot ALTER a constraint, so alembic needs the
        # copy-and-move strategy. Without it the whole chain aborts here on any
        # SQLite-backed deployment (dev/test) before reaching later migrations.
        with op.batch_alter_table(TABLE) as batch:
            batch.create_unique_constraint(CONSTRAINT, ["org_id", "channel_message_id"])


def downgrade():
    if _has_constraint(op.get_bind()):
        # Symmetric with upgrade(): in SQLite batch mode alembic materialises the
        # unique constraint as a unique INDEX, and SQLite has no
        # ALTER TABLE ... DROP CONSTRAINT, so the bare form raised on any
        # SQLite deployment.
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_constraint(CONSTRAINT, type_="unique")
