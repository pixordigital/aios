import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, ForeignKey, Integer, String, Table, Text
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aios.db.engine import Base


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- Mixins ---

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class OrgScopedMixin:
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)


# --- Organization ---

class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)

    users = relationship("User", back_populates="organization")
    agents = relationship("Agent", back_populates="organization")
    teams = relationship("Team", back_populates="organization")
    channels = relationship("ChannelConnection", back_populates="organization")


# Pixor owner org always holds the unlimited plan. One choke point — every ORM
# write (register, billing upgrade/downgrade, admin edits) flows through flush,
# so a before_flush hook beats guarding each call site.
_PIXOR_SLUG = "pixor"


def _pixor_is_unlimited(org: "Organization") -> None:
    # Force every flush, not just the first: billing downgrade sets plan="free"
    # and must be overridden again. Guard on slug, not on the flag.
    if org.slug == _PIXOR_SLUG and org.extra_data.get("plan") != "unlimited":
        org.extra_data["plan"] = "unlimited"
        org.extra_data["unlimited"] = True


from sqlalchemy import event  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

@event.listens_for(Session, "before_flush")
def _org_before_flush(session, context, instances):
    for org in session.new:
        if isinstance(org, Organization):
            _pixor_is_unlimited(org)
    for org in session.dirty:
        if isinstance(org, Organization):
            _pixor_is_unlimited(org)


# --- User ---

class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    api_key_hash: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    role: Mapped[str] = mapped_column(String(50), default="admin")
    email_verified: Mapped[bool] = mapped_column(default=False)

    organization = relationship("Organization", back_populates="users")


# --- Agent ---

class Agent(Base, TimestampMixin, OrgScopedMixin):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    agent_type: Mapped[str] = mapped_column(String(50), default="custom")
    llm_config: Mapped[dict] = mapped_column(JSON, default=dict)
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    tools: Mapped[list] = mapped_column(JSON, default=list)
    memory_config: Mapped[dict] = mapped_column(JSON, default=lambda: {
        "short_term": {"max_messages": 50},
        "long_term": {"enabled": True, "top_k": 5},
        "episodic": {"enabled": True, "summarize_after": 10},
    })
    governance_config: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="draft")

    organization = relationship("Organization", back_populates="agents")
    instances = relationship("AgentInstance", back_populates="agent")
    memories = relationship("Memory", back_populates="agent")


class AgentInstance(Base, TimestampMixin):
    __tablename__ = "agent_instances"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="idle")
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)

    agent = relationship("Agent", back_populates="instances")


# --- Team ---

team_agents = Table(
    "team_agents",
    Base.metadata,
    Column("team_id", String(36), ForeignKey("teams.id"), primary_key=True),
    Column("agent_id", String(36), ForeignKey("agents.id"), primary_key=True),
    Column("priority", Integer, default=0),
)


class Team(Base, TimestampMixin, OrgScopedMixin):
    __tablename__ = "teams"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    routing_strategy: Mapped[str] = mapped_column(String(50), default="supervisor")
    orchestrator_agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    manager_agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)

    organization = relationship("Organization", back_populates="teams")
    agents = relationship("Agent", secondary=team_agents, lazy="selectin")
    orchestrator_agent = relationship("Agent", foreign_keys=[orchestrator_agent_id])
    manager_agent = relationship("Agent", foreign_keys=[manager_agent_id])


# --- Conversation ---

class Conversation(Base, TimestampMixin, OrgScopedMixin):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    channel_connection_id: Mapped[str | None] = mapped_column(ForeignKey("channel_connections.id"), nullable=True)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(50), default="web")
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)

    messages = relationship("Message", back_populates="conversation", order_by="Message.created_at")


class Message(Base, TimestampMixin):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text, default="")
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    tool_calls: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    channel_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)

    conversation = relationship("Conversation", back_populates="messages")


# --- Channel Connection ---

class ChannelConnection(Base, TimestampMixin, OrgScopedMixin):
    __tablename__ = "channel_connections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    channel_type: Mapped[str] = mapped_column(String(50))
    label: Mapped[str] = mapped_column(String(255))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(default=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id"), nullable=True)

    organization = relationship("Organization", back_populates="channels")


# --- Tool ---

class Tool(Base, TimestampMixin, OrgScopedMixin):
    __tablename__ = "tools"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    input_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    code_reference: Mapped[str] = mapped_column(String(255), default="")
    is_builtin: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20), default="active")


# --- Invitation ---

class Artifact(Base, TimestampMixin):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), index=True, nullable=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(default=0)
    storage_path: Mapped[str] = mapped_column(String(1000))
    description: Mapped[str] = mapped_column(Text, default="")
    searchable_content: Mapped[str] = mapped_column(Text, default="")


class UsageRecord(Base):
    __tablename__ = "usage_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    messages: Mapped[int] = mapped_column(default=0)
    llm_tokens: Mapped[int] = mapped_column(default=0)
    llm_calls: Mapped[int] = mapped_column(default=0)


class RemoteInstance(Base, TimestampMixin):
    __tablename__ = "remote_instances"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    base_url: Mapped[str] = mapped_column(String(500))
    api_key: Mapped[str] = mapped_column(String(500), default="")
    client_org_id: Mapped[str] = mapped_column(String(36), default="")
    is_active: Mapped[bool] = mapped_column(default=True)
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(50), index=True)
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)


class Invitation(Base, TimestampMixin):
    __tablename__ = "invitations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[str] = mapped_column(String(50), default="member")
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True, default=_uuid)
    accepted: Mapped[bool] = mapped_column(default=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=True)

class Memory(Base, TimestampMixin):
    __tablename__ = "memories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    type: Mapped[str] = mapped_column(String(50))
    content: Mapped[str] = mapped_column(Text, default="")
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)

    agent = relationship("Agent", back_populates="memories")


class AgentMetric(Base):
    """Per-agent performance metrics — aggregated hourly."""
    __tablename__ = "agent_metrics"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    hour: Mapped[str] = mapped_column(String(13), index=True)  # YYYY-MM-DD-HH
    messages: Mapped[int] = mapped_column(default=0)
    tokens: Mapped[int] = mapped_column(default=0)
    errors: Mapped[int] = mapped_column(default=0)
    avg_response_ms: Mapped[int] = mapped_column(default=0)
    tool_calls: Mapped[int] = mapped_column(default=0)


class PendingAction(Base, TimestampMixin):
    """Human-in-the-loop approval queue for agent tool calls."""
    __tablename__ = "pending_actions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(255))
    tool_args: Mapped[dict] = mapped_column(JSON, default=dict)
    context_summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected|expired
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Skill(Base, TimestampMixin, OrgScopedMixin):
    """Reusable skill patterns extracted from successful agent runs."""
    __tablename__ = "skills"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    skill_type: Mapped[str] = mapped_column(String(50), default="tool_pattern")
    content: Mapped[str] = mapped_column(Text, default="")
    input_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    usage_count: Mapped[int] = mapped_column(default=0)
    success_rate: Mapped[float] = mapped_column(default=1.0)
    source_conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)

    agent = relationship("Agent")


class OAuthAccount(Base, TimestampMixin):
    __tablename__ = "oauth_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)  # "google" | "github"
    provider_user_id: Mapped[str] = mapped_column(String(255), index=True)
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)


class DeadLetter(Base, TimestampMixin):
    """Failed inbound/outbound messages awaiting manual retry."""
    __tablename__ = "dead_letters"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), index=True, nullable=True)
    channel_type: Mapped[str] = mapped_column(String(50))
    channel_connection_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), index=True, nullable=True)
    direction: Mapped[str] = mapped_column(String(20))  # inbound|outbound
    job_name: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # full args to re-run job
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="failed")  # failed|retried|resolved
    retried_at: Mapped[datetime | None] = mapped_column(nullable=True)
