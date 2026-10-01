"""sales_funnels + funnel_insights: shared Sales/Data deal pipeline

A funnel is a named pipeline that both teams work: Sales owns the stage ladder
and deal movement, the Data team posts findings. Deals attach through
CrmDeal.pipeline (existing column), so adopting an existing pipeline as a
funnel needs no deal migration.
"""

revision = "z6a7b8c9d0e1"
down_revision = "y5z6a7b8c9d0"

from alembic import op
import sqlalchemy as sa


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    if not _has_table("sales_funnels"):
        op.create_table(
            "sales_funnels",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text, nullable=False, server_default=""),
            sa.Column("pipeline", sa.String(50), nullable=False, server_default="default", index=True),
            sa.Column("sales_agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=True),
            sa.Column("data_agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("extra_data", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )
    if not _has_table("funnel_insights"):
        op.create_table(
            "funnel_insights",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("funnel_id", sa.String(36), sa.ForeignKey("sales_funnels.id"), nullable=False, index=True),
            sa.Column("finding", sa.Text, nullable=False),
            sa.Column("stage", sa.String(30), nullable=False, server_default=""),
            sa.Column("recommendation", sa.Text, nullable=False, server_default=""),
            sa.Column("author_id", sa.String(36), nullable=True),
            sa.Column("author_type", sa.String(20), nullable=False, server_default="agent"),
            sa.Column("resolved", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )


def downgrade():
    for t in ("funnel_insights", "sales_funnels"):
        if _has_table(t):
            op.drop_table(t)
