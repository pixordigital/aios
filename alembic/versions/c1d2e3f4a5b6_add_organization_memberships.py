"""add organization_memberships table

Revision ID: c1d2e3f4a5b6
Revises: b2c3d4e5f6a7
Create Date: 2026-11-26
"""

from alembic import op
import sqlalchemy as sa


revision = "c1d2e3f4a5b6"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    if not _has_table("organization_memberships"):
        op.create_table(
            "organization_memberships",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "org_id",
                sa.String(36),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(50), nullable=False, server_default="admin"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "org_id", name="uq_org_membership_user_org"),
        )
        op.create_index("ix_org_memberships_user_id", "organization_memberships", ["user_id"])
        op.create_index("ix_org_memberships_org_id", "organization_memberships", ["org_id"])


def downgrade():
    if _has_table("organization_memberships"):
        op.drop_index("ix_org_memberships_org_id", table_name="organization_memberships")
        op.drop_index("ix_org_memberships_user_id", table_name="organization_memberships")
        op.drop_table("organization_memberships")
