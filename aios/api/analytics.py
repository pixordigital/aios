from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Agent, Conversation, Message, Organization, Memory, ChannelConnection
from aios.schemas import BaseModel
from aios.core.cache import cache
from aios.core.tracing import METRICS
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
async def get_trace_api(
    trace_id: str,
    user=Depends(get_current_user),
    org_id: str = Depends(get_org_id),
):
    """Return all spans for a given trace ID, scoped to the caller's org."""
    from fastapi import HTTPException

    from aios.core.tracing import get_trace_scoped

    spans = get_trace_scoped(trace_id, org_id)
    if spans is None:
        raise HTTPException(404, "trace not found")
    return {"trace_id": trace_id, "spans": spans}


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
    """Per-agent metrics from persisted rows (identical in every worker)."""
    rows = await _agent_health_rows(db, org_id)
    return {"agents": rows}


async def _agent_health_rows(db: DatabaseBackend, org_id: str) -> list[dict]:
    """DB-backed deploy + runtime status, scoped to org.

    The old version read `telemetry`/`health_tracker`, both process-local: with
    2 gunicorn workers (and an ARQ worker running the actual agents) the
    dashboard usually saw an empty tracker, and the endpoint returned every
    tenant's agents because the tracker does not store org_id.
    """
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d-%H")

    from aios.db.models import AgentInstance, AgentMetric

    agents = (
        await db.execute(select(Agent).where(Agent.org_id == org_id).order_by(Agent.name))
    ).scalars().all()
    if not agents:
        return []

    metric_rows = (
        await db.execute(
            select(
                AgentMetric.agent_id,
                func.sum(AgentMetric.messages),
                func.sum(AgentMetric.tokens),
                func.sum(AgentMetric.errors),
                func.sum(AgentMetric.tool_calls),
                func.avg(AgentMetric.avg_response_ms),
            )
            .where(AgentMetric.org_id == org_id, AgentMetric.hour >= since)
            .group_by(AgentMetric.agent_id)
        )
    ).all()
    metrics = {
        r[0]: {
            "messages": int(r[1] or 0),
            "tokens": int(r[2] or 0),
            "errors": int(r[3] or 0),
            "tool_calls": int(r[4] or 0),
            "avg_response_ms": int(r[5] or 0),
        }
        for r in metric_rows
    }

    instances = (
        await db.execute(
            select(AgentInstance)
            .where(AgentInstance.org_id == org_id, AgentInstance.agent_id.in_([a.id for a in agents]))
            .order_by(AgentInstance.created_at.desc())
        )
    ).scalars().all()
    latest: dict[str, AgentInstance] = {}
    for inst in instances:
        latest.setdefault(inst.agent_id, inst)

    return [
        _health_entry(a, metrics.get(a.id, {}), latest.get(a.id))
        for a in agents
    ]


def _health_entry(agent: Agent, metric: dict, inst) -> dict:
    messages = metric.get("messages", 0)
    errors = metric.get("errors", 0)
    avg_ms = metric.get("avg_response_ms", 0)
    error_rate = round(errors / messages * 100, 1) if messages else 0.0

    evidence = (inst.extra_data or {}) if inst else {}
    if not inst or "verified" not in evidence:
        deploy_status = "none" if agent.status != "active" else "unverified"
    elif evidence.get("verified"):
        deploy_status = "verified"
    else:
        deploy_status = "failed"

    if agent.status != "active":
        status = "failed" if deploy_status == "failed" else "draft"
    elif deploy_status == "failed":
        status = "degraded"
    elif deploy_status == "unverified":
        status = "unverified"
    elif messages == 0:
        status = "no_traffic"
    elif error_rate > 5.0 or avg_ms > 5000:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "agent_id": agent.id,
        "name": agent.name,
        "agent_status": agent.status,
        "status": status,
        "deploy_status": deploy_status,
        "messages": messages,
        "tokens": metric.get("tokens", 0),
        "errors": errors,
        "error_rate_pct": error_rate,
        "avg_response_ms": avg_ms,
        "tool_calls": metric.get("tool_calls", 0),
        "failures": errors,
        "successes": max(messages - errors, 0),
        "verified_at": evidence.get("verified_at"),
        "latency_ms": evidence.get("latency_ms"),
        "model": evidence.get("model"),
        "last_deploy_error": evidence.get("error"),
    }


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
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    """Agent health for this org only, derived from persisted rows."""
    return {"agents": await _agent_health_rows(db, org_id)}


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
        from aios.core.whatsapp_guard import _warmup_limits
        import time
        per_min, per_hour, per_day = _warmup_limits(instance, time.time())
        return {"instance": instance, "per_min": per_min, "per_hour": per_hour, "per_day": per_day, "status": "ok"}
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
