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
        op.create_unique_constraint(CONSTRAINT, TABLE, ["org_id", "channel_message_id"])


def downgrade():
    if _has_constraint(op.get_bind()):
        op.drop_constraint(CONSTRAINT, TABLE, type_="unique")
