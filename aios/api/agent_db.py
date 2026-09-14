"""AgentDB API — knowledge, learnings, reflections (Ruflo AgentDB pattern)."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from aios.api.deps import get_current_user, get_org_id
from aios.core.agent_db import agent_db
from aios.db.models import User

router = APIRouter(prefix="/api/agent-db", tags=["agent-db"])


# ── Knowledge ──

class KnowledgeCreate(BaseModel):
    agent_id: str
    knowledge_type: str = Field(default="fact", max_length=50)
    key: str = Field(min_length=1, max_length=255)
    value: str = ""
    confidence: float = Field(default=1.0, ge=0, le=1)
    source: str = "agent"
    tags: list[str] = Field(default_factory=list)
    extra_data: dict = Field(default_factory=dict)


@router.post("/knowledge")
async def create_knowledge(
    body: KnowledgeCreate,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    row = await agent_db.put_knowledge(
        agent_id=body.agent_id, org_id=org_id, knowledge_type=body.knowledge_type,
        key=body.key, value=body.value, confidence=body.confidence,
        source=body.source, tags=body.tags, extra_data=body.extra_data,
    )
    return row


@router.get("/knowledge")
async def list_knowledge(
    agent_id: str = "", q: str = "", knowledge_type: str = "",
    limit: int = Query(20, ge=1, le=100),
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    rows = await agent_db.search_knowledge(org_id=org_id, agent_id=agent_id, q=q, knowledge_type=knowledge_type, limit=limit)
    return {"items": rows}


@router.get("/knowledge/similar")
async def similar_knowledge(
    agent_id: str, q: str,
    limit: int = Query(5, ge=1, le=20),
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    rows = await agent_db.similar_knowledge(org_id=org_id, agent_id=agent_id, query_text=q, limit=limit)
    return {"items": rows}


# ── Learnings ──

class LearningCreate(BaseModel):
    agent_id: str
    learning_type: str = Field(default="success_pattern")
    trigger_context: str = ""
    action_taken: str = ""
    outcome: str = ""
    success: bool = True
    metrics: dict = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0, le=1)
    tags: list[str] = Field(default_factory=list)


@router.post("/learnings")
async def create_learning(
    body: LearningCreate,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    row = await agent_db.record_learning(
        agent_id=body.agent_id, org_id=org_id, learning_type=body.learning_type,
        trigger_context=body.trigger_context, action_taken=body.action_taken,
        outcome=body.outcome, success=body.success, metrics=body.metrics,
        confidence=body.confidence, tags=body.tags,
    )
    return row


@router.get("/learnings")
async def list_learnings(
    agent_id: str = "", learning_type: str = "", limit: int = Query(20, ge=1, le=100),
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    rows = await agent_db.list_learnings(org_id=org_id, agent_id=agent_id, learning_type=learning_type, limit=limit)
    return {"items": rows}


@router.get("/learnings/top")
async def top_patterns(
    agent_id: str = "", limit: int = Query(10, ge=1, le=50),
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    rows = await agent_db.top_patterns(org_id=org_id, agent_id=agent_id, limit=limit)
    return {"items": rows}


# ── Reflections ──

class ReflectionCreate(BaseModel):
    agent_id: str
    conversation_id: str | None = None
    task_summary: str = ""
    what_went_well: str = ""
    what_could_improve: str = ""
    key_insight: str = ""
    action_items: list[str] = Field(default_factory=list)
    score: float = Field(default=0, ge=0, le=1)
    tokens_used: int = 0


@router.post("/reflections")
async def create_reflection(
    body: ReflectionCreate,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    row = await agent_db.create_reflection(
        agent_id=body.agent_id, org_id=org_id, conversation_id=body.conversation_id,
        task_summary=body.task_summary, what_went_well=body.what_went_well,
        what_could_improve=body.what_could_improve, key_insight=body.key_insight,
        action_items=body.action_items, score=body.score, tokens_used=body.tokens_used,
    )
    return row


@router.get("/reflections")
async def list_reflections(
    agent_id: str = "", limit: int = Query(20, ge=1, le=100),
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    rows = await agent_db.list_reflections(org_id=org_id, agent_id=agent_id, limit=limit)
    return {"items": rows}


@router.get("/stats")
async def agent_db_stats(
    agent_id: str = "",
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    return await agent_db.stats(org_id=org_id, agent_id=agent_id)
