"""governance config, OAuth accounts, tenant hardening (org_id on messages/memories/agent_instances)"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "9051a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Agent governance config ---
    op.add_column("agents", sa.Column("governance_config", sa.JSON, nullable=False, server_default="'{}'::json"))

    # --- User email verification ---
    op.add_column("users", sa.Column("email_verified", sa.Boolean, nullable=False, server_default="false"))
    op.create_index("ix_users_api_key_hash", "users", ["api_key_hash"], unique=False)

    # --- Tenant hardening: org_id on messages, memories, agent_instances ---
    # These tables need org_id for direct tenant isolation (previously only accessible via parent join).

    # For messages: backfill org_id from conversations, then make non-nullable
    op.add_column("messages", sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=True))
    op.execute("""
        UPDATE messages SET org_id = (
            SELECT conversations.org_id FROM conversations
            WHERE conversations.id = messages.conversation_id
        )
    """)
    op.alter_column("messages", "org_id", nullable=False)
    op.create_index("ix_messages_org_id", "messages", ["org_id"], unique=False)

    # For memories: backfill org_id from agents, then make non-nullable
    op.add_column("memories", sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=True))
    op.execute("""
        UPDATE memories SET org_id = (
            SELECT agents.org_id FROM agents
            WHERE agents.id = memories.agent_id
        )
    """)
    op.alter_column("memories", "org_id", nullable=False)
    op.create_index("ix_memories_org_id", "memories", ["org_id"], unique=False)

    # For agent_instances: backfill org_id from agents, then make non-nullable
    op.add_column("agent_instances", sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=True))
    op.execute("""
        UPDATE agent_instances SET org_id = (
            SELECT agents.org_id FROM agents
            WHERE agents.id = agent_instances.agent_id
        )
    """)
    op.alter_column("agent_instances", "org_id", nullable=False)
    op.create_index("ix_agent_instances_org_id", "agent_instances", ["org_id"], unique=False)

    # --- OAuth accounts table ---
    op.create_table(
        "oauth_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), index=True, nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_user_id", sa.String(255), nullable=False),
        sa.Column("extra_data", sa.JSON, nullable=False, server_default="'{}'::json"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("oauth_accounts")
    op.drop_index("ix_agent_instances_org_id", "agent_instances")
    op.drop_column("agent_instances", "org_id")
    op.drop_index("ix_memories_org_id", "memories")
    op.drop_column("memories", "org_id")
    op.drop_index("ix_messages_org_id", "messages")
    op.drop_column("messages", "org_id")
    op.drop_index("ix_users_api_key_hash", "users")
    op.drop_column("users", "email_verified")
    op.drop_column("agents", "governance_config")
