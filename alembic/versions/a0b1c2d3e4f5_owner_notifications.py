"""owner_notifications: Slack→Telegram escalation state.

One row per owner-facing message that may need a fallback. `acked_at` is set
when the owner reacts or replies in the originating channel; `escalated_at`
when Telegram got the duplicate after the ack window expired.
"""

revision = "a0b1c2d3e4f5"
down_revision = "z6a7b8c9d0e1"

from alembic import op
import sqlalchemy as sa


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    if not _has_table("owner_notifications"):
        op.create_table(
            "owner_notifications",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("channel_type", sa.String(20), nullable=False),
            sa.Column("target", sa.String(255), nullable=False),
            sa.Column("body", sa.Text, nullable=False, server_default=""),
            sa.Column("urgency", sa.String(20), nullable=False, server_default="info"),
            sa.Column("requires_ack", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("deadline_at", sa.DateTime, nullable=True),
            sa.Column("acked_at", sa.DateTime, nullable=True),
            sa.Column("escalated_at", sa.DateTime, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )


def downgrade():
    if _has_table("owner_notifications"):
        op.drop_table("owner_notifications")
