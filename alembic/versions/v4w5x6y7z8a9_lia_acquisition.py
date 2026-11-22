"""LIA lead-acquisition tables and deterministic contact eligibility."""

revision = "v4w5x6y7z8a9"
down_revision = "u3v4w5x6y7z8"

from alembic import op
import sqlalchemy as sa


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _ts():
    return [
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    ]


def upgrade():
    if not _has_table("lead_sources"):
        op.create_table(
            "lead_sources",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("source_type", sa.String(40), nullable=False),
            sa.Column("url", sa.String(500), nullable=False, server_default=""),
            sa.Column("terms_notes", sa.Text, nullable=False, server_default=""),
            sa.Column("allowed_for_outreach", sa.Boolean, nullable=False, server_default=sa.false()),
            *_ts(),
        )
    if not _has_table("lead_signals"):
        op.create_table(
            "lead_signals",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("account_id", sa.String(36), sa.ForeignKey("crm_accounts.id"), nullable=True),
            sa.Column("source_id", sa.String(36), sa.ForeignKey("lead_sources.id"), nullable=True),
            sa.Column("signal_type", sa.String(80), nullable=False),
            sa.Column("value", sa.Text, nullable=False, server_default=""),
            sa.Column("confidence", sa.Float, nullable=False, server_default="0"),
            sa.Column("observed_at", sa.DateTime, nullable=False),
            sa.Column("provenance", sa.JSON, nullable=False, server_default="{}"),
            *_ts(),
        )
        op.create_index("ix_lead_signals_account_id", "lead_signals", ["account_id"])
    if not _has_table("lead_campaigns"):
        op.create_table(
            "lead_campaigns",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("channel", sa.String(40), nullable=False, server_default="email"),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("icp_profile", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("budget_brl", sa.Float, nullable=False, server_default="0"),
            sa.Column("approved_by", sa.String(36), nullable=True),
            sa.Column("legal_reviewed", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("start_at", sa.DateTime, nullable=True),
            sa.Column("end_at", sa.DateTime, nullable=True),
            *_ts(),
        )
    if not _has_table("lead_campaign_members"):
        op.create_table(
            "lead_campaign_members",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("campaign_id", sa.String(36), sa.ForeignKey("lead_campaigns.id"), nullable=False, index=True),
            sa.Column("account_id", sa.String(36), sa.ForeignKey("crm_accounts.id"), nullable=True),
            sa.Column("contact_id", sa.String(36), sa.ForeignKey("crm_contacts.id"), nullable=True),
            sa.Column("stage", sa.String(40), nullable=False, server_default="company_discovery"),
            sa.Column("disposition", sa.String(30), nullable=False, server_default="research_required", index=True),
            sa.Column("icp_fit", sa.Float, nullable=False, server_default="0"),
            sa.Column("solution_fit", sa.Float, nullable=False, server_default="0"),
            sa.Column("buying_readiness", sa.Float, nullable=False, server_default="0"),
            sa.Column("evidence_confidence", sa.Float, nullable=False, server_default="0"),
            sa.UniqueConstraint("campaign_id", "contact_id", name="uq_campaign_contact"),
            *_ts(),
        )
    if not _has_table("outreach_messages"):
        op.create_table(
            "outreach_messages",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("campaign_id", sa.String(36), sa.ForeignKey("lead_campaigns.id"), nullable=True),
            sa.Column("contact_id", sa.String(36), sa.ForeignKey("crm_contacts.id"), nullable=False),
            sa.Column("channel", sa.String(40), nullable=False, server_default="email"),
            sa.Column("subject", sa.String(255), nullable=False, server_default=""),
            sa.Column("body", sa.Text, nullable=False, server_default=""),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("approved_by", sa.String(36), nullable=True),
            sa.Column("sent_at", sa.DateTime, nullable=True),
            sa.Column("reply_class", sa.String(40), nullable=False, server_default=""),
            *_ts(),
        )
    if not _has_table("suppression_entries"):
        op.create_table(
            "suppression_entries",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False, server_default="email"),
            sa.Column("value", sa.String(255), nullable=False),
            sa.Column("reason", sa.String(60), nullable=False, server_default="opt_out"),
            sa.UniqueConstraint("org_id", "kind", "value", name="uq_suppression_org_value"),
            *_ts(),
        )
        op.create_index("ix_suppression_entries_value", "suppression_entries", ["value"])


def downgrade():
    for t in (
        "suppression_entries",
        "outreach_messages",
        "lead_campaign_members",
        "lead_campaigns",
        "lead_signals",
        "lead_sources",
    ):
        if _has_table(t):
            op.drop_table(t)
