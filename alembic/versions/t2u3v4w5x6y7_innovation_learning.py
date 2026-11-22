"""Innovation accounting: hypotheses, experiments, learning scoreboard."""

revision = "t2u3v4w5x6y7"
down_revision = "s1t2u3v4w5x6"

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
    if not _has_table("hypotheses"):
        op.create_table(
            "hypotheses",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("department_id", sa.String(36), sa.ForeignKey("departments.id"), nullable=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False, server_default="value"),
            sa.Column("statement", sa.Text, nullable=False, server_default=""),
            sa.Column("riskiest_assumption", sa.Text, nullable=False, server_default=""),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft", index=True),
            sa.Column("evidence_summary", sa.Text, nullable=False, server_default=""),
            *_ts(),
        )
    if not _has_table("experiments"):
        op.create_table(
            "experiments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("hypothesis_id", sa.String(36), sa.ForeignKey("hypotheses.id"), nullable=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("mvp_type", sa.String(30), nullable=False, server_default="experimental_prototype"),
            sa.Column("riskiest_assumption", sa.Text, nullable=False, server_default=""),
            sa.Column("metric_name", sa.String(120), nullable=False, server_default=""),
            sa.Column("baseline", sa.Float, nullable=True),
            sa.Column("observed", sa.Float, nullable=True),
            sa.Column("sample_size", sa.Integer, nullable=False, server_default="0"),
            sa.Column("success_threshold", sa.Float, nullable=True),
            sa.Column("direction", sa.String(10), nullable=False, server_default="increase"),
            sa.Column("cost_cap_brl", sa.Float, nullable=False, server_default="0"),
            sa.Column("spent_brl", sa.Float, nullable=False, server_default="0"),
            sa.Column("time_cap_days", sa.Integer, nullable=False, server_default="0"),
            sa.Column("owner_id", sa.String(36), nullable=True),
            sa.Column("stop_conditions", sa.Text, nullable=False, server_default=""),
            sa.Column("permissions", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("privacy_reviewed", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("result", sa.String(20), nullable=False, server_default="pending", index=True),
            sa.Column("interpretation", sa.Text, nullable=False, server_default=""),
            sa.Column("decision", sa.String(20), nullable=True),
            sa.Column("started_at", sa.DateTime, nullable=True),
            sa.Column("ended_at", sa.DateTime, nullable=True),
            *_ts(),
        )


def downgrade():
    for t in ("experiments", "hypotheses"):
        if _has_table(t):
            op.drop_table(t)
