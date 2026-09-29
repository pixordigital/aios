"""sales_goals table for monthly targets (internal tool)."""

revision = "s4l3sg0a1s01"
down_revision = "97c400a6f914"

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        "sales_goals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("year_month", sa.String(7), nullable=False),
        sa.Column("target_brl", sa.Float(), server_default="0"),
        sa.Column("team_id", sa.String(36), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_sales_goals_year_month", "sales_goals", ["year_month"])
    op.create_index("ix_sales_goals_team", "sales_goals", ["team_id"])


def downgrade():
    op.drop_index("ix_sales_goals_team", table_name="sales_goals")
    op.drop_index("ix_sales_goals_year_month", table_name="sales_goals")
    op.drop_table("sales_goals")
