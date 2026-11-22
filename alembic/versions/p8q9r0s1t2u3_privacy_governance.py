"""LGPD processing registry and data-subject request workflow."""

revision = "p8q9r0s1t2u3"
down_revision = "o7p8q9r0s1t2"

from alembic import op
import sqlalchemy as sa


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    if not _has_table("processing_activities"):
        op.create_table(
            "processing_activities",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("activity_key", sa.String(120), nullable=False),
            sa.Column("version", sa.Integer, nullable=False, server_default="1"),
            sa.Column("role", sa.String(20), nullable=False, server_default="controller"),
            sa.Column("owner_id", sa.String(36), nullable=True),
            sa.Column("purpose", sa.Text, nullable=False, server_default=""),
            sa.Column("data_subjects", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("data_categories", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("sensitive_data", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("source", sa.String(255), nullable=False, server_default=""),
            sa.Column("legal_basis", sa.String(40), nullable=False, server_default=""),
            sa.Column("legal_basis_evidence", sa.Text, nullable=False, server_default=""),
            sa.Column("necessity_assessment", sa.Text, nullable=False, server_default=""),
            sa.Column("recipients", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("vendors", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("locations", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("international_transfers", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("transfer_mechanism", sa.String(120), nullable=False, server_default=""),
            sa.Column("notice", sa.Text, nullable=False, server_default=""),
            sa.Column("retention_days", sa.Integer, nullable=False, server_default="0"),
            sa.Column("rights_route", sa.String(255), nullable=False, server_default=""),
            sa.Column("safeguards", sa.Text, nullable=False, server_default=""),
            sa.Column("ripd_status", sa.String(30), nullable=False, server_default="not_required"),
            sa.Column("policy_version", sa.String(40), nullable=False, server_default=""),
            sa.Column("approved_by", sa.String(36), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint("org_id", "activity_key", "version", name="uq_processing_activity_version"),
        )
    if not _has_table("privacy_requests"):
        op.create_table(
            "privacy_requests",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("subject_identifier", sa.String(255), nullable=False, index=True),
            sa.Column("request_type", sa.String(20), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="received", index=True),
            sa.Column("received_at", sa.DateTime, nullable=False),
            sa.Column("due_at", sa.DateTime, nullable=True),
            sa.Column("completed_at", sa.DateTime, nullable=True),
            sa.Column("scope", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("evidence", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("rejection_reason", sa.Text, nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )


def downgrade():
    for t in ("privacy_requests", "processing_activities"):
        if _has_table(t):
            op.drop_table(t)
