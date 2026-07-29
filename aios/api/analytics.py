from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Agent, Conversation, Message
from aios.schemas import BaseModel
from aios.core.cache import cache
from aios.core.tracing import get_trace, METRICS
from .deps import get_org_id

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


class OverviewOut(BaseModel):
    total_agents: int
    active_agents: int
    total_conversations: int
    total_messages: int


@router.get("/overview", response_model=OverviewOut)
async def overview(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    agent_count = await db.execute(
        select(func.count(Agent.id)).where(Agent.org_id == org_id)
    )
    active_count = await db.execute(
        select(func.count(Agent.id)).where(
            Agent.org_id == org_id, Agent.status == "active"
        )
    )
    conv_count = await db.execute(
        select(func.count(Conversation.id)).where(Conversation.org_id == org_id)
    )
    msg_count = await db.execute(
        select(func.count(Message.id)).where(Conversation.org_id == org_id).select_from(Message).join(Conversation)
    )
    return OverviewOut(
        total_agents=agent_count.scalar() or 0,
        active_agents=active_count.scalar() or 0,
        total_conversations=conv_count.scalar() or 0,
        total_messages=msg_count.scalar() or 0,
    )


@router.get("/trace/{trace_id}")
async def get_trace_api(trace_id: str):
    """Return all spans for a given trace ID."""
    return {"trace_id": trace_id, "spans": get_trace(trace_id)}


@router.get("/metrics")
async def get_metrics():
    """Return in-memory metrics counters."""
    from aios.core.tools import ToolEngine
    return {
        "llm": dict(METRICS),
        "cache": cache.stats(),
        "tools": ToolEngine.audit_summary(),
    }
