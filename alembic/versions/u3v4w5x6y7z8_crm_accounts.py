"""CRM account/contact model and unified interaction timeline."""

revision = "u3v4w5x6y7z8"
down_revision = "t2u3v4w5x6y7"

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
    if not _has_table("crm_accounts"):
        op.create_table(
            "crm_accounts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("cnpj", sa.String(18), nullable=True),
            sa.Column("industry", sa.String(120), nullable=False, server_default=""),
            sa.Column("website", sa.String(500), nullable=False, server_default=""),
            sa.Column("size", sa.String(40), nullable=False, server_default=""),
            sa.Column("status", sa.String(30), nullable=False, server_default="prospect"),
            sa.Column("owner_agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=True),
            sa.Column("health_score", sa.Float, nullable=False, server_default="0.5"),
            sa.Column("lifetime_value", sa.Float, nullable=False, server_default="0"),
            sa.Column("extra_data", sa.JSON, nullable=False, server_default="{}"),
            sa.UniqueConstraint("org_id", "cnpj", name="uq_crm_account_org_cnpj"),
            *_ts(),
        )
        op.create_index("ix_crm_accounts_cnpj", "crm_accounts", ["cnpj"])
    if not _has_table("crm_contacts"):
        op.create_table(
            "crm_contacts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("account_id", sa.String(36), sa.ForeignKey("crm_accounts.id"), nullable=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("email", sa.String(255), nullable=False, server_default=""),
            sa.Column("phone", sa.String(40), nullable=False, server_default=""),
            sa.Column("role", sa.String(160), nullable=False, server_default=""),
            sa.Column("source", sa.String(120), nullable=False, server_default=""),
            sa.Column("is_decision_maker", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("email_verified", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("contact_allowed", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("lawful_basis", sa.String(40), nullable=False, server_default=""),
            sa.Column("opt_out_at", sa.DateTime, nullable=True),
            sa.Column("extra_data", sa.JSON, nullable=False, server_default="{}"),
            sa.UniqueConstraint("org_id", "email", name="uq_crm_contact_org_email"),
            *_ts(),
        )
        op.create_index("ix_crm_contacts_account_id", "crm_contacts", ["account_id"])
    if not _has_table("crm_interactions"):
        op.create_table(
            "crm_interactions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("account_id", sa.String(36), sa.ForeignKey("crm_accounts.id"), nullable=True),
            sa.Column("contact_id", sa.String(36), sa.ForeignKey("crm_contacts.id"), nullable=True),
            sa.Column("deal_id", sa.String(36), sa.ForeignKey("crm_deals.id"), nullable=True),
            sa.Column("channel", sa.String(40), nullable=False, server_default="manual"),
            sa.Column("direction", sa.String(20), nullable=False, server_default="outbound"),
            sa.Column("event_type", sa.String(60), nullable=False, server_default="message"),
            sa.Column("summary", sa.Text, nullable=False, server_default=""),
            sa.Column("occurred_at", sa.DateTime, nullable=False, index=True),
            sa.Column("source", sa.String(120), nullable=False, server_default=""),
            sa.Column("provenance", sa.JSON, nullable=False, server_default="{}"),
            *_ts(),
        )
        op.create_index("ix_crm_interactions_account_id", "crm_interactions", ["account_id"])
        op.create_index("ix_crm_interactions_contact_id", "crm_interactions", ["contact_id"])
        op.create_index("ix_crm_interactions_deal_id", "crm_interactions", ["deal_id"])


def downgrade():
    for t in ("crm_interactions", "crm_contacts", "crm_accounts"):
        if _has_table(t):
            op.drop_table(t)
