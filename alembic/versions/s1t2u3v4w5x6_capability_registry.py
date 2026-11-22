"""Capability registry and solution-fit dispositions."""

revision = "s1t2u3v4w5x6"
down_revision = "r0s1t2u3v4w5"

from alembic import op
import sqlalchemy as sa


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    if not _has_table("capabilities"):
        op.create_table(
            "capabilities",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=True),
            sa.Column("capability_key", sa.String(120), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("maturity", sa.String(20), nullable=False, server_default="concept", index=True),
            sa.Column("supported_use_cases", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("integrations", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("complexity", sa.String(20), nullable=False, server_default="medium"),
            sa.Column("limitations", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("dependencies", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("pricing_notes", sa.Text, nullable=False, server_default=""),
            sa.Column("deployment_evidence", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("is_commercially_available", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint("org_id", "capability_key", name="uq_capability_org_key"),
        )
    if not _has_table("solution_fit_assessments"):
        op.create_table(
            "solution_fit_assessments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("subject_type", sa.String(20), nullable=False, server_default="company"),
            sa.Column("subject_id", sa.String(36), nullable=False, index=True),
            sa.Column("capability_id", sa.String(36), sa.ForeignKey("capabilities.id"), nullable=True),
            sa.Column("problem_fit", sa.Float, nullable=False, server_default="0"),
            sa.Column("capability_fit", sa.Float, nullable=False, server_default="0"),
            sa.Column("feasibility", sa.Float, nullable=False, server_default="0"),
            sa.Column("commercial_viability", sa.Float, nullable=False, server_default="0"),
            sa.Column("buying_readiness", sa.Float, nullable=False, server_default="0"),
            sa.Column("evidence_confidence", sa.Float, nullable=False, server_default="0"),
            sa.Column("contact_allowed", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("disposition", sa.String(30), nullable=False, server_default="research_required", index=True),
            sa.Column("rationale", sa.Text, nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )


def downgrade():
    for t in ("solution_fit_assessments", "capabilities"):
        if _has_table(t):
            op.drop_table(t)
