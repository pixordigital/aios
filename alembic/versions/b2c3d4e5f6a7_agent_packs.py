"""agent packs: pack, version, activation

Revision ID: b2c3d4e5f6a7
Revises: e1f2a3b4c5d6
Create Date: 2026-11-25
"""

from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _pending_actions_columns() -> dict[str, dict]:
    if not _has_table("pending_actions"):
        return {}
    return {c["name"]: c for c in sa.inspect(op.get_bind()).get_columns("pending_actions")}


def upgrade():
    cols = _pending_actions_columns()
    nullable_updates = [
        name for name in ("agent_id", "conversation_id")
        if name in cols and cols[name].get("nullable") is False
    ]
    if nullable_updates:
        with op.batch_alter_table("pending_actions") as batch_op:
            for name in nullable_updates:
                batch_op.alter_column(name, existing_type=sa.String(36), nullable=True)

    if not _has_table("agent_packs"):
        op.create_table(
            "agent_packs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("pack_key", sa.String(128), nullable=False, index=True),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column("description", sa.Text, nullable=False, server_default=""),
            sa.Column("agent_type", sa.String(64), nullable=False, server_default=""),
            sa.Column("active_version_id", sa.String(36), nullable=True, index=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("extra_data", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint("org_id", "pack_key", name="uq_agent_packs_org_pack_key"),
        )

    if not _has_table("agent_pack_versions"):
        op.create_table(
            "agent_pack_versions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("pack_id", sa.String(36), sa.ForeignKey("agent_packs.id"), nullable=False, index=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("version_semver", sa.String(32), nullable=False),
            sa.Column("version_num", sa.Integer, nullable=False, server_default="1"),
            sa.Column("manifest_json", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("checksum_sha256", sa.String(64), nullable=False, server_default="", index=True),
            sa.Column("fingerprint_sha256", sa.String(64), nullable=False, server_default="", index=True),
            sa.Column("capability_loss_json", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("provenance_json", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("extra_data", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint("pack_id", "version_semver", name="uq_agent_pack_versions_pack_semver"),
        )

    if not _has_table("agent_pack_activations"):
        op.create_table(
            "agent_pack_activations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("pack_id", sa.String(36), sa.ForeignKey("agent_packs.id"), nullable=False, index=True),
            sa.Column("version_id", sa.String(36), sa.ForeignKey("agent_pack_versions.id"), nullable=False, index=True),
            sa.Column("from_version_id", sa.String(36), sa.ForeignKey("agent_pack_versions.id"), nullable=True),
            sa.Column("to_version_id", sa.String(36), sa.ForeignKey("agent_pack_versions.id"), nullable=True),
            sa.Column("approval_action_id", sa.String(36), nullable=True, index=True),
            sa.Column("action_type", sa.String(30), nullable=False, server_default="activate"),
            sa.Column("status", sa.String(30), nullable=False, server_default="requested", index=True),
            sa.Column("requested_by", sa.String(36), nullable=True),
            sa.Column("decided_by", sa.String(36), nullable=True),
            sa.Column("requested_at", sa.DateTime, nullable=False),
            sa.Column("decided_at", sa.DateTime, nullable=True),
            sa.Column("applied_at", sa.DateTime, nullable=True),
            sa.Column("error", sa.Text, nullable=False, server_default=""),
            sa.Column("extra_data", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )


def downgrade():
    for t in ("agent_pack_activations", "agent_pack_versions", "agent_packs"):
        if _has_table(t):
            op.drop_table(t)

    cols = _pending_actions_columns()
    restore = []
    for name in ("agent_id", "conversation_id"):
        if name not in cols or cols[name].get("nullable") is not True:
            continue
        null_count = op.get_bind().execute(
            sa.text(f"SELECT COUNT(*) FROM pending_actions WHERE {name} IS NULL")
        ).scalar_one()
        # Real approval rows legitimately have NULL links; never invent identity
        # or delete them just to satisfy the pre-upgrade NOT NULL contract.
        if not int(null_count or 0):
            restore.append(name)
    if restore:
        with op.batch_alter_table("pending_actions") as batch_op:
            for name in restore:
                batch_op.alter_column(name, existing_type=sa.String(36), nullable=False)
