from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Agent, AgentInstance, Conversation, Message, Organization
from aios.schemas import BaseModel
from aios.core.cache import cache
from aios.core.tracing import get_trace, METRICS
from aios.core.agent_health import health_tracker
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


# ─── Telemetry Endpoints ───


@router.get("/telemetry/summary")
async def telemetry_summary(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    """Org-wide telemetry summary."""
    from aios.core.telemetry import telemetry
    return telemetry.get_org_summary(org_id)


@router.get("/telemetry/agents")
async def telemetry_agents(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    """Per-agent performance metrics."""
    from aios.core.telemetry import telemetry
    agents = telemetry.get_all_agents_summary(org_id)

    # enrich with agent names and health status
    agent_ids = [a["agent_id"] for a in agents]
    if agent_ids:
        agent_objs = (await db.execute(
            select(Agent).where(Agent.id.in_(agent_ids))
        )).scalars().all()
        name_map = {a.id: a.name for a in agent_objs}
        for a in agents:
            a["name"] = name_map.get(a["agent_id"], "Unknown")
            a["health"] = health_tracker.get_status(a["agent_id"])

    return {"agents": agents}


@router.get("/telemetry/agent/{agent_id}")
async def telemetry_agent(
    agent_id: str,
    hours: int = 24,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    """Hourly metrics for a specific agent."""
    from aios.core.telemetry import telemetry

    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        from fastapi import HTTPException
        raise HTTPException(404)

    metrics = telemetry.get_metrics_for_agent(agent_id, hours)
    health = health_tracker.get_status(agent_id)

    return {
        "agent_id": agent_id,
        "agent_name": agent.name,
        "health": health,
        "metrics": metrics,
    }


@router.get("/telemetry/health")
async def telemetry_health(
    org_id: str = Depends(get_org_id),
):
    """Agent health status for all agents in org."""
    all_health = health_tracker.all_status()
    # filter to org (health tracker doesn't store org_id, return all)
    return {"agents": list(all_health.values())}


@router.post("/telemetry/flush")
async def telemetry_flush():
    """Manually flush telemetry metrics to DB."""
    from aios.core.telemetry import telemetry
    await telemetry.flush_to_db()
    return {"status": "flushed"}
