"""initial - all tables."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "8c9907080a72"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), unique=True, index=True, nullable=False),
        sa.Column("extra_data", sa.JSON, default=dict),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, index=True, nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("api_key_hash", sa.String(255), nullable=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("role", sa.String(50), default="admin"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "agents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("agent_type", sa.String(50), default="custom"),
        sa.Column("llm_config", sa.JSON, default=dict),
        sa.Column("system_prompt", sa.Text, default=""),
        sa.Column("tools", sa.JSON, default=list),
        sa.Column("memory_config", sa.JSON, default=dict),
        sa.Column("status", sa.String(20), default="draft"),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), index=True, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "agent_instances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("status", sa.String(20), default="idle"),
        sa.Column("extra_data", sa.JSON, default=dict),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "teams",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("routing_strategy", sa.String(50), default="supervisor"),
        sa.Column("orchestrator_agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("manager_agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("extra_data", sa.JSON, default=dict),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), index=True, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "team_agents",
        sa.Column("team_id", sa.String(36), sa.ForeignKey("teams.id"), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), primary_key=True),
        sa.Column("priority", sa.Integer, default=0),
    )
    op.create_table(
        "channel_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("channel_type", sa.String(50), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("config", sa.JSON, default=dict),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("team_id", sa.String(36), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), index=True, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("channel_connection_id", sa.String(36), sa.ForeignKey("channel_connections.id"), nullable=True),
        sa.Column("team_id", sa.String(36), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("channel", sa.String(50), default="web"),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("extra_data", sa.JSON, default=dict),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), index=True, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), index=True, nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, default=""),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("tool_calls", sa.JSON, nullable=True),
        sa.Column("tool_results", sa.JSON, nullable=True),
        sa.Column("channel_message_id", sa.String(255), nullable=True),
        sa.Column("extra_data", sa.JSON, default=dict),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "tools",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), unique=True, nullable=False),
        sa.Column("description", sa.Text, default=""),
        sa.Column("input_schema", sa.JSON, default=dict),
        sa.Column("output_schema", sa.JSON, default=dict),
        sa.Column("code_reference", sa.String(255), default=""),
        sa.Column("is_builtin", sa.Boolean, default=False),
        sa.Column("status", sa.String(20), default="active"),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), index=True, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "memories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), index=True, nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("content", sa.Text, default=""),
        sa.Column("extra_data", sa.JSON, default=dict),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("memories")
    op.drop_table("tools")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("channel_connections")
    op.drop_table("team_agents")
    op.drop_table("teams")
    op.drop_table("agent_instances")
    op.drop_table("agents")
    op.drop_table("users")
    op.drop_table("organizations")
