"""whatsapp_contacts + whatsapp_events: durable guard state and risk signals

The WhatsApp guard kept opt-outs, cooldowns and rate counters in module-level
dicts. Every deploy wiped them, so a number that sent STOP could be messaged
again immediately after a restart. There was also nowhere to record an actual
ban signal (403/429/disconnect from Evolution), so the existing risk_score stub
had no data to work from.

whatsapp_contacts holds the durable per-number state.
whatsapp_events is an append-only feed the risk score reads.
"""

revision = "w3x4y5z6a7b8"
down_revision = "v2w3x4y5z6a7"

from alembic import op
import sqlalchemy as sa

CONTACT = "whatsapp_contacts"
EVENT = "whatsapp_events"


def upgrade():
    bind = op.get_bind()
    have = set(sa.inspect(bind).get_table_names())

    if CONTACT not in have:
        op.create_table(
            CONTACT,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), nullable=False),
            sa.Column("number", sa.String(20), nullable=False),
            sa.Column("state", sa.String(20), nullable=False, server_default="active"),
            sa.Column("reason", sa.String(64), nullable=False, server_default=""),
            sa.Column("until", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("org_id", "number", name="uq_whatsapp_contact_org_number"),
        )
        op.create_index("ix_whatsapp_contacts_number", CONTACT, ["number"])

    if EVENT not in have:
        op.create_table(
            EVENT,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), nullable=False),
            sa.Column("instance", sa.String(80), nullable=False, server_default=""),
            sa.Column("kind", sa.String(30), nullable=False),
            sa.Column("detail", sa.String(200), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_whatsapp_events_instance", EVENT, ["instance"])
        op.create_index("ix_whatsapp_events_kind", EVENT, ["kind"])
        op.create_index("ix_whatsapp_events_created_at", EVENT, ["created_at"])


def downgrade():
    bind = op.get_bind()
    have = set(sa.inspect(bind).get_table_names())
    if EVENT in have:
        op.drop_table(EVENT)
    if CONTACT in have:
        op.drop_table(CONTACT)
