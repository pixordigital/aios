"""Pydantic schemas with input validation."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# --- Auth ---

class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=6, max_length=128)
    org_name: str = Field(default="Default", min_length=1, max_length=100)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str = ""
    token_type: str = "bearer"
    user_id: str
    org_id: str


# --- User ---

class UserOut(BaseModel):
    id: str
    email: str
    role: str
    org_id: str
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


# --- Organization ---

class OrganizationOut(BaseModel):
    id: str
    name: str
    slug: str
    extra_data: dict
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


# --- Agent ---

_AGENT_LLM_CONFIG_DEFAULT = {
    "model": "openai/gpt-4o", "temperature": 0.7, "max_tokens": 4096,
}
_AGENT_MEMORY_DEFAULT = {
    "short_term": {"max_messages": 50},
    "long_term": {"enabled": True, "top_k": 5},
    "episodic": {"enabled": True, "summarize_after": 10},
}


_GOVERNANCE_DEFAULT = {
    "autonomy": "draft",  # autonomous | draft | ask
    "max_tokens_per_run": 500_000,
    "allowed_tools": "__all__",  # "__all__" or list of tool names
    "denied_tools": [],
    "max_iterations": 10,
}


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    agent_type: str = Field(default="custom", max_length=50)
    system_prompt: str = Field(default="", max_length=100000)
    llm_config: dict = Field(default_factory=lambda: dict(_AGENT_LLM_CONFIG_DEFAULT))
    tools: list[str] = Field(default_factory=list, max_length=50)
    memory_config: dict = Field(default_factory=lambda: dict(_AGENT_MEMORY_DEFAULT))
    governance_config: dict = Field(default_factory=lambda: dict(_GOVERNANCE_DEFAULT))


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    system_prompt: str | None = Field(default=None, max_length=100000)
    llm_config: dict | None = None
    tools: list[str] | None = Field(default=None, max_length=50)
    memory_config: dict | None = None
    governance_config: dict | None = None
    status: str | None = Field(default=None, max_length=20)


class AgentOut(BaseModel):
    id: str
    name: str
    agent_type: str
    system_prompt: str
    llm_config: dict
    tools: list
    memory_config: dict
    governance_config: dict
    status: str
    org_id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# --- Team ---

class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    routing_strategy: str = Field(default="supervisor", max_length=50)
    extra_data: dict = Field(default_factory=dict)


class TeamOut(BaseModel):
    id: str
    name: str
    routing_strategy: str
    extra_data: dict
    org_id: str
    agents: list = []
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class TeamAssignRequest(BaseModel):
    agent_ids: list[str] = Field(min_length=1, max_length=100)


# --- Conversation ---

class ConversationCreate(BaseModel):
    agent_id: str | None = None
    team_id: str | None = None
    channel: str = "web"
    external_id: str | None = None


class ConversationOut(BaseModel):
    id: str
    channel: str
    external_id: str | None = None
    agent_id: str | None = None
    team_id: str | None = None
    extra_data: dict
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    agent_id: str | None = None
    tool_calls: dict | None = None
    tool_results: dict | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class MessageSend(BaseModel):
    content: str = Field(min_length=1, max_length=100000)


class SendMessageResponse(BaseModel):
    user_message: MessageOut
    reply: MessageOut | None = None


# --- Channel ---

class ChannelCreate(BaseModel):
    channel_type: str = Field(max_length=50)
    label: str = Field(min_length=1, max_length=255)
    config: dict = Field(default_factory=dict)
    agent_id: str | None = None
    team_id: str | None = None


class ChannelUpdate(BaseModel):
    label: str | None = None
    config: dict | None = None
    is_active: bool | None = None
    agent_id: str | None = None
    team_id: str | None = None


class ChannelOut(BaseModel):
    id: str
    channel_type: str
    label: str
    is_active: bool
    agent_id: str | None = None
    team_id: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
