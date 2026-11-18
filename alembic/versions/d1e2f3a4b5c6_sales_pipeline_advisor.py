"""Persist internal sales pipeline advisor assessments."""
revision = "d1e2f3a4b5c6"
down_revision = "c2d3e4f5a6b7"

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        "sales_pipeline_assessments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="interview"),
        sa.Column("answers", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("crm_evidence", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("proposal", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("funnel_id", sa.String(36), sa.ForeignKey("sales_funnels.id"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade():
    op.drop_table("sales_pipeline_assessments")
