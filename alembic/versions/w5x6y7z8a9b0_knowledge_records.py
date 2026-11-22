"""Knowledge records with provenance and permission-aware retrieval."""

revision = "w5x6y7z8a9b0"
down_revision = "v4w5x6y7z8a9"

from alembic import op
import sqlalchemy as sa


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    if not _has_table("knowledge_records"):
        op.create_table(
            "knowledge_records",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("department_id", sa.String(36), sa.ForeignKey("departments.id"), nullable=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("content", sa.Text, nullable=False, server_default=""),
            sa.Column("kind", sa.String(20), nullable=False, server_default="statement", index=True),
            sa.Column("classification", sa.String(20), nullable=False, server_default="internal", index=True),
            sa.Column("source_type", sa.String(60), nullable=False, server_default=""),
            sa.Column("source_id", sa.String(120), nullable=False, server_default=""),
            sa.Column("provenance", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("derived_from", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("account_id", sa.String(36), sa.ForeignKey("crm_accounts.id"), nullable=True),
            sa.Column("retention_until", sa.DateTime, nullable=True),
            sa.Column("deleted_at", sa.DateTime, nullable=True),
            sa.Column("search_text", sa.Text, nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )
        op.create_index("ix_knowledge_records_account_id", "knowledge_records", ["account_id"])


def downgrade():
    if _has_table("knowledge_records"):
        op.drop_table("knowledge_records")
