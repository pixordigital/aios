"""AI SOC: incidents and detection telemetry (independent evidence store)."""

revision = "q9r0s1t2u3v4"
down_revision = "p8q9r0s1t2u3"

from alembic import op
import sqlalchemy as sa


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    if not _has_table("security_incidents"):
        op.create_table(
            "security_incidents",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("incident_key", sa.String(120), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("category", sa.String(80), nullable=False, server_default=""),
            sa.Column("severity", sa.String(20), nullable=False, server_default="medium"),
            sa.Column("status", sa.String(20), nullable=False, server_default="detected"),
            sa.Column("detected_at", sa.DateTime, nullable=False),
            sa.Column("acknowledged_at", sa.DateTime, nullable=True),
            sa.Column("contained_at", sa.DateTime, nullable=True),
            sa.Column("recovered_at", sa.DateTime, nullable=True),
            sa.Column("closed_at", sa.DateTime, nullable=True),
            sa.Column("personal_data_involved", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("privacy_handoff_at", sa.DateTime, nullable=True),
            sa.Column("external_notification_by", sa.String(36), nullable=True),
            sa.Column("evidence", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("timeline", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint("org_id", "incident_key", name="uq_security_incident_key"),
        )
        op.create_index("ix_security_incidents_severity", "security_incidents", ["severity"])
        op.create_index("ix_security_incidents_status", "security_incidents", ["status"])
    if not _has_table("security_events"):
        op.create_table(
            "security_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("source", sa.String(80), nullable=False, server_default=""),
            sa.Column("event_type", sa.String(80), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
            sa.Column("incident_id", sa.String(36), sa.ForeignKey("security_incidents.id"), nullable=True),
            sa.Column("actor_type", sa.String(10), nullable=True),
            sa.Column("actor_id", sa.String(36), nullable=True),
            sa.Column("payload", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )
        op.create_index("ix_security_events_source", "security_events", ["source"])
        op.create_index("ix_security_events_event_type", "security_events", ["event_type"])


def downgrade():
    for t in ("security_events", "security_incidents"):
        if _has_table(t):
            op.drop_table(t)
