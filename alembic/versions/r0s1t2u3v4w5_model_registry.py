"""Model registry + deterministic cost-per-success optimisation."""

revision = "r0s1t2u3v4w5"
down_revision = "q9r0s1t2u3v4"

from alembic import op
import sqlalchemy as sa


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    if not _has_table("model_registry"):
        op.create_table(
            "model_registry",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=True),
            sa.Column("model_key", sa.String(160), nullable=False),
            sa.Column("provider", sa.String(80), nullable=False),
            sa.Column("tier", sa.Integer, nullable=False, server_default="1"),
            sa.Column("input_price_per_1m", sa.Float, nullable=False, server_default="0"),
            sa.Column("output_price_per_1m", sa.Float, nullable=False, server_default="0"),
            sa.Column("price_currency", sa.String(8), nullable=False, server_default="USD"),
            sa.Column("quality_score", sa.Float, nullable=False, server_default="0"),
            sa.Column("reliability", sa.Float, nullable=False, server_default="1"),
            sa.Column("latency_p95_ms", sa.Integer, nullable=False, server_default="0"),
            sa.Column("capabilities", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("context_window", sa.Integer, nullable=False, server_default="0"),
            sa.Column("privacy_ok", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("contract_ok", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("approved", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("config_version", sa.String(40), nullable=False, server_default="1"),
            sa.Column("notes", sa.Text, nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint("org_id", "model_key", name="uq_model_registry_org_key"),
        )


def downgrade():
    if _has_table("model_registry"):
        op.drop_table("model_registry")
