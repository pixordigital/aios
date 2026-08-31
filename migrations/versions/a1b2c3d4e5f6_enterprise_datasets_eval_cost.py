"""enterprise datasets eval_runs workflow cost"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("cases", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("extra_data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
    )
    op.create_index("ix_datasets_org_id", "datasets", ["org_id"])
    op.create_index("ix_datasets_agent_id", "datasets", ["agent_id"])

    op.create_table(
        "eval_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("agent_id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=True),
        sa.Column("version_id", sa.String(length=36), nullable=True),
        sa.Column("judge_model", sa.String(length=100), nullable=False),
        sa.Column("avg_score", sa.Float(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("extra_data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
    )
    op.create_index("ix_eval_runs_agent_id", "eval_runs", ["agent_id"])
    op.create_index("ix_eval_runs_org_id", "eval_runs", ["org_id"])

    try:
        op.add_column("workflow_runs", sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"))
        op.add_column("workflow_runs", sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0.0"))
    except Exception:
        pass
    try:
        op.add_column("usage_records", sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0.0"))
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_column("usage_records", "cost_usd")
    except Exception:
        pass
    try:
        op.drop_column("workflow_runs", "cost_usd")
        op.drop_column("workflow_runs", "tokens")
    except Exception:
        pass
    op.drop_table("eval_runs")
    op.drop_table("datasets")
