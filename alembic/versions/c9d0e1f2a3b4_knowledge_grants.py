"""Explicit revocable grants for confidential KnowledgeRecords."""

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"

from alembic import op
import sqlalchemy as sa


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    if _has_table("knowledge_grants"):
        return
    op.create_table(
        "knowledge_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("record_id", sa.String(36), sa.ForeignKey("knowledge_records.id"), nullable=False),
        sa.Column("granted_by", sa.String(36), nullable=True),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
        sa.Column("expires_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("org_id", "user_id", "record_id", name="uq_knowledge_grant_actor_record"),
    )
    op.create_index("ix_knowledge_grants_org_id", "knowledge_grants", ["org_id"])
    op.create_index("ix_knowledge_grants_user_id", "knowledge_grants", ["user_id"])
    op.create_index("ix_knowledge_grants_record_id", "knowledge_grants", ["record_id"])


def downgrade():
    if _has_table("knowledge_grants"):
        op.drop_table("knowledge_grants")
