"""Persist weekly sales reports and recommendation follow-up."""
revision = "e7f8a9b0c1d2"
down_revision = "d1e2f3a4b5c6"

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        "weekly_sales_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("week_start", sa.DateTime(), nullable=False),
        sa.Column("week_end", sa.DateTime(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("email_status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("org_id", "week_start", name="uq_weekly_sales_report_org_week"),
    )
    op.create_index("ix_weekly_sales_reports_org_id", "weekly_sales_reports", ["org_id"])
    op.create_index("ix_weekly_sales_reports_week_start", "weekly_sales_reports", ["week_start"])
    op.create_table(
        "weekly_sales_recommendations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("report_id", sa.String(36), sa.ForeignKey("weekly_sales_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("action", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_url", sa.String(500), nullable=False, server_default="/dashboard/crm"),
        sa.Column("tried", sa.Boolean(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_weekly_sales_recommendations_org_id", "weekly_sales_recommendations", ["org_id"])
    op.create_index("ix_weekly_sales_recommendations_report_id", "weekly_sales_recommendations", ["report_id"])


def downgrade():
    op.drop_table("weekly_sales_recommendations")
    op.drop_table("weekly_sales_reports")
