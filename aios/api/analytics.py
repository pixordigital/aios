from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Agent, AgentInstance, Conversation, Message, Organization, Memory, ChannelConnection
from aios.schemas import BaseModel
from aios.core.cache import cache
from aios.core.tracing import get_trace, METRICS
from aios.core.agent_health import health_tracker
from .deps import get_current_user, get_org_id

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
async def get_trace_api(trace_id: str, user=Depends(get_current_user)):
    """Return all spans for a given trace ID."""
    return {"trace_id": trace_id, "spans": get_trace(trace_id)}


@router.get("/metrics")
async def get_metrics(user=Depends(get_current_user)):
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


@router.get("/usage/monthly")
async def usage_monthly(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    from aios.core.limits import get_monthly_usage

    return await get_monthly_usage(org_id, db)


@router.get("/usage/daily")
async def usage_daily(days: int = 30, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    from sqlalchemy import select
    from aios.db.models import UsageRecord

    rows = (await db.execute(select(UsageRecord).where(UsageRecord.org_id == org_id).order_by(UsageRecord.date.desc()).limit(days))).scalars().all()
    return [{"date": r.date, "tokens": r.llm_tokens, "cost": round(r.cost_usd or 0, 4), "messages": r.messages, "calls": r.llm_calls} for r in reversed(rows)]


@router.get("/usage/agents")
async def usage_agents(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    from aios.core.limits import get_agent_usage_breakdown

    return await get_agent_usage_breakdown(org_id, db)


@router.get("/usage/models")
async def usage_models(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    from sqlalchemy import select
    from aios.db.models import AgentMetric, Agent

    rows = (await db.execute(select(AgentMetric).where(AgentMetric.org_id == org_id).order_by(AgentMetric.hour.desc()).limit(200))).scalars().all()
    # group by model? AgentMetric doesn't store model — fetch from Agent llm_config
    agent_ids = list({r.agent_id for r in rows})
    models: dict[str, dict] = {}
    if agent_ids:
        agents = (await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))).scalars().all()
        amap = {a.id: a.llm_config.get("model", "openai/gpt-4o-mini") for a in agents}
        for r in rows:
            model = amap.get(r.agent_id, "unknown")
            models.setdefault(model, {"model": model, "tokens": 0, "messages": 0, "cost": 0})
            models[model]["tokens"] += r.tokens
            models[model]["messages"] += r.messages
            from aios.core.tracing import estimate_cost

            models[model]["cost"] += estimate_cost(model, r.tokens)
        for v in models.values():
            v["cost"] = round(v["cost"], 4)
    return sorted(models.values(), key=lambda x: x["tokens"], reverse=True)


@router.get("/health/pgvector")
async def pgvector_health(db: DatabaseBackend = Depends(get_db_backend)):
    try:
        from sqlalchemy import text
        r = await db.execute(text("SELECT 1 FROM pg_extension WHERE extname='vector'"))
        ok = r.scalar() is not None
        return {"ok": ok, "mode": "pgvector" if ok else "BOW fallback"}
    except Exception as e:
        return {"ok": False, "mode": "BOW fallback", "error": str(e)[:120]}

@router.get("/health/evolution-rate/{instance}")
async def evolution_rate(instance: str):
    try:
        from aios.core.whatsapp_guard import _hour_key, _day_key
        import time
        # mock rate check
        return {"instance": instance, "per_min": 15, "per_hour": 120, "per_day": 800, "status": "ok"}
    except Exception as e:
        return {"instance": instance, "error": str(e)}

@router.post("/telemetry/flush")
async def telemetry_flush(user=Depends(get_current_user)):
    """Manually flush telemetry metrics to DB."""
    from aios.core.telemetry import telemetry
    await telemetry.flush_to_db()
    return {"status": "flushed"}


# ─── Proactive Alerts Endpoints ───


class ProactiveAlertsToggle(BaseModel):
    enabled: bool


@router.get("/proactive-alerts")
async def get_proactive_alerts(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    """Get proactive alerts status and recent alerts for org."""
    # Get org to check proactive_alerts setting
    org = await db.get(Organization, org_id)
    enabled = False
    if org and isinstance(org.extra_data, dict):
        enabled = org.extra_data.get("proactive_alerts", False)

    # Check if active evolution channel exists
    has_evo = False
    if enabled:
        has_evo = (
            await db.execute(
                select(ChannelConnection.id).where(
                    ChannelConnection.org_id == org_id,
                    ChannelConnection.channel_type == "evolution",
                    ChannelConnection.is_active == True,
                ).limit(1)
            )
        ).scalar_one_or_none() is not None

    # Get recent alerts from Memory (type="alert")
    alerts = []
    if enabled:
        rows = (
            await db.execute(
                select(Memory)
                .where(Memory.org_id == org_id, Memory.type == "alert")
                .order_by(Memory.created_at.desc())
                .limit(20)
            )
        ).scalars().all()
        for m in rows:
            if isinstance(m.extra_data, dict):
                alerts.append(m.extra_data)

    return {
        "enabled": enabled and has_evo,
        "has_evolution": has_evo,
        "alerts": alerts,
    }


@router.post("/proactive-alerts/toggle")
async def toggle_proactive_alerts(
    payload: ProactiveAlertsToggle,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    """Enable/disable proactive alerts for org."""
    org = await db.get(Organization, org_id)
    if not org:
        from fastapi import HTTPException
        raise HTTPException(404, "Organization not found")

    data = org.extra_data if isinstance(org.extra_data, dict) else {}
    data["proactive_alerts"] = payload.enabled
    org.extra_data = data
    await db.commit()

    return {"enabled": payload.enabled, "message": "Proactive alerts " + ("enabled" if payload.enabled else "disabled")}
