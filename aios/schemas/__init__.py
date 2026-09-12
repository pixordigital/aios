"""Pydantic schemas with input validation."""

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, EmailStr, Field, field_validator

T = TypeVar("T")


class PageResponse(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False
    total: int | None = None


# --- Auth ---

class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=6, max_length=128)
    org_name: str = Field(default="Default", min_length=1, max_length=100)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=1, max_length=128)
    totp_code: str | None = Field(default=None, max_length=6)


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
    "autonomy": "autonomous",  # autonomous | draft | ask — 100% autônomo com HITL
    "autonomous": True,  # flag 100% autônomo (ReAct+Reflexion 3 trials)
    "max_trials": 3,  # Reflexion trials
    "hitl_enabled": True,
    "hitl_value_threshold": 5000,
    "hitl_discount_threshold": 10,  # % desconto que exige aprovação humana
    "max_tokens_per_run": 500_000,
    "allowed_tools": "__all__",  # "__all__" or list of tool names
    "denied_tools": [],
    "max_iterations": 10,
}


AgentType = Literal["custom", "orchestrator", "manager", "sdr", "closer", "support", "data_analyst", "data_scientist"]


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    agent_type: AgentType = Field(default="custom")
    system_prompt: str = Field(default="", max_length=100000)
    llm_config: dict = Field(default_factory=lambda: dict(_AGENT_LLM_CONFIG_DEFAULT))
    tools: list[str] = Field(default_factory=list, max_length=50)
    memory_config: dict = Field(default_factory=lambda: dict(_AGENT_MEMORY_DEFAULT))
    governance_config: dict = Field(default_factory=lambda: dict(_GOVERNANCE_DEFAULT))

    @field_validator("tools")
    @classmethod
    def _validate_tools(cls, v: list[str]) -> list[str]:
        if not v:
            return v
        try:
            from aios.tools.registry import TOOL_REGISTRY
            allowed = set(TOOL_REGISTRY.keys())
            if not allowed:
                raise ImportError
        except Exception:
            # fallback list when registry not yet populated
            allowed = {"calculator","web_search","send_email","read_file","current_datetime","http_get","http_request","code","transform","if_branch","wait","hubspot","pipedrive","rdstation","transcribe","voice_call","crm_create_deal","crm_update_deal","lead_score","sql_query","python_sandbox","crm","lead_scoring","dynamic"}
        invalid = [t for t in v if t not in allowed]
        if invalid:
            raise ValueError(f"tools inválidas: {invalid}")
        return v

    @field_validator("llm_config")
    @classmethod
    def _validate_llm(cls, v: dict) -> dict:
        if not isinstance(v, dict):
            raise ValueError("llm_config deve ser dict")
        t = v.get("temperature")
        if t is not None and not (isinstance(t, (int, float)) and 0 <= float(t) <= 2):
            raise ValueError("temperature deve ser 0..2")
        mt = v.get("max_tokens")
        if mt is not None and not (isinstance(mt, int) and 256 <= mt <= 16384):
            raise ValueError("max_tokens deve ser 256..16384")
        return v


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    agent_type: AgentType | None = None
    system_prompt: str | None = Field(default=None, max_length=100000)
    llm_config: dict | None = None
    tools: list[str] | None = Field(default=None, max_length=50)
    memory_config: dict | None = None
    governance_config: dict | None = None
    status: str | None = Field(default=None, max_length=20)

    @field_validator("tools")
    @classmethod
    def _validate_tools(cls, v: list[str] | None) -> list[str] | None:
        if v is None or not v:
            return v
        try:
            from aios.tools.registry import TOOL_REGISTRY
            allowed = set(TOOL_REGISTRY.keys())
            if not allowed:
                raise ImportError
        except Exception:
            allowed = {"calculator","web_search","send_email","read_file","current_datetime","http_get","http_request","code","transform","if_branch","wait","hubspot","pipedrive","rdstation","transcribe","voice_call","crm_create_deal","crm_update_deal","lead_score","sql_query","python_sandbox"}
        invalid = [t for t in v if t not in allowed]
        if invalid:
            raise ValueError(f"tools inválidas: {invalid}")
        return v

    @field_validator("llm_config")
    @classmethod
    def _validate_llm(cls, v: dict | None) -> dict | None:
        if v is None:
            return v
        if not isinstance(v, dict):
            raise ValueError("llm_config deve ser dict")
        t = v.get("temperature")
        if t is not None and not (isinstance(t, (int, float)) and 0 <= float(t) <= 2):
            raise ValueError("temperature deve ser 0..2")
        mt = v.get("max_tokens")
        if mt is not None and not (isinstance(mt, int) and 256 <= mt <= 16384):
            raise ValueError("max_tokens deve ser 256..16384")
        return v


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


# --- Approval ---

class ApprovalDecision(BaseModel):
    action_id: str
    decision: str = Field(pattern=r"^(approve|reject)$")


class PendingActionOut(BaseModel):
    id: str
    agent_id: str
    conversation_id: str
    tool_name: str
    tool_args: dict
    context_summary: str
    status: str
    created_at: float

    model_config = {"from_attributes": True}


# --- Skill ---

class SkillCreate(BaseModel):
    agent_id: str
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    skill_type: str = "tool_pattern"
    content: str = ""
    input_schema: dict = {}
    tags: list[str] = []


class SkillOut(BaseModel):
    id: str
    agent_id: str
    name: str
    description: str
    skill_type: str
    content: str
    tags: list
    usage_count: int
    success_rate: float
    org_id: str
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


# --- Thread ---

class ThreadOut(BaseModel):
    """Thread = conversation for user-facing API clarity."""
    id: str
    name: str
    channel: str
    agent_id: str | None = None
    created_at: str = ""
    message_count: int = 0


# --- Rubric ---

class RubricCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    criteria: list[str] = []
    weights: dict = {}


class RubricScore(BaseModel):
    rubric_id: str
    response: str = Field(min_length=1, max_length=100000)
