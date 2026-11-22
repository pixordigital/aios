from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Agent, Conversation, CrmDeal, Message, Organization, Memory, ChannelConnection
from aios.schemas import BaseModel
from aios.core.cache import cache
from aios.core.tracing import METRICS
from aios.core.agent_health import health_tracker
from aios.governance.kpi import (
    average_deal_size,
    conversion_rate,
    governance_kpis_snapshot,
    interpret_kpis,
    kpi_catalog,
    list_kpi_targets,
    set_kpi_target,
    validate_target_proposal,
    win_rate,
)
from .deps import get_current_user, get_org_id, get_superadmin

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
async def get_metrics(user=Depends(get_superadmin)):
    """Return in-memory process-global metrics counters.

    Superadmin-only: counters aggregate across processes/tenants and have no
    org scope. Do not treat as tenant KPI.
    """
    from aios.core.tools import ToolEngine
    return {
        "scope": "process_global",
        "tenant_scoped": False,
        "caveats": [
            "Process-global counters; not org-scoped and not a tenant KPI.",
            "Values may include multiple tenants/workers and reset on process restart.",
        ],
        "llm": dict(METRICS),
        "cache": cache.stats(),
        "tools": ToolEngine.audit_summary(),
    }


# ─── Business outcome analytics ───

# First-response latency needs the first user and first assistant row of each
# conversation, which is a per-conversation min() — expensive to express portably
# across SQLite and Postgres. The window keeps it bounded; it is a sample of the
# most recent conversations, and the response says so.
_OUTCOME_WINDOW = 500


def _utcnow() -> datetime:
    """Naive UTC, matching how TimestampMixin stores datetimes."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _outcome_snapshot(
    db: DatabaseBackend,
    org_id: str,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict:
    """Outcome counts for one time window. Every value is read from rows."""
    from aios.db.models import CrmDeal, PendingAction
    from aios.verticals.pet_business.metrics import OutcomeCounts, summarize_outcomes

    conv_q = select(Conversation.id).where(Conversation.org_id == org_id)
    if since:
        conv_q = conv_q.where(Conversation.created_at >= since)
    if until:
        conv_q = conv_q.where(Conversation.created_at < until)
    conv_ids = list(
        (
            await db.execute(
                conv_q.order_by(Conversation.created_at.desc()).limit(_OUTCOME_WINDOW)
            )
        ).scalars().all()
    )

    enquiries = len(conv_ids)
    answered = 0
    first_response_seconds: list[float] = []
    if conv_ids:
        msg_rows = (
            await db.execute(
                select(Message.conversation_id, Message.role, Message.created_at)
                .where(
                    Message.org_id == org_id,
                    Message.conversation_id.in_(conv_ids),
                    Message.role.in_(("user", "assistant")),
                )
                .order_by(Message.conversation_id, Message.created_at)
            )
        ).all()
        first: dict[str, dict[str, object]] = {}
        for conv_id, role, created_at in msg_rows:
            slot = first.setdefault(conv_id, {})
            slot.setdefault(role, created_at)
        for slot in first.values():
            user_at = slot.get("user")
            assistant_at = slot.get("assistant")
            if assistant_at is not None:
                answered += 1
                if user_at is not None:
                    delta = (assistant_at - user_at).total_seconds()
                    if delta >= 0:
                        first_response_seconds.append(delta)

    deal_q = select(
        func.count(CrmDeal.id), func.coalesce(func.sum(CrmDeal.value), 0.0)
    ).where(CrmDeal.org_id == org_id)
    if since:
        deal_q = deal_q.where(CrmDeal.created_at >= since)
    if until:
        deal_q = deal_q.where(CrmDeal.created_at < until)
    qualified = int((await db.execute(deal_q)).scalar() or 0)

    attr_q = select(
        func.count(CrmDeal.id), func.coalesce(func.sum(CrmDeal.value), 0.0)
    ).where(CrmDeal.org_id == org_id, CrmDeal.agent_id.is_not(None))
    if since:
        attr_q = attr_q.where(CrmDeal.created_at >= since)
    if until:
        attr_q = attr_q.where(CrmDeal.created_at < until)
    attributed_rows = (await db.execute(attr_q)).one()
    attributed = int(attributed_rows[0] or 0)
    attributed_value = float(attributed_rows[1] or 0.0)

    handoff_q = (
        select(func.count(func.distinct(PendingAction.conversation_id)))
        .where(PendingAction.org_id == org_id)
    )
    if since:
        handoff_q = handoff_q.where(PendingAction.created_at >= since)
    if until:
        handoff_q = handoff_q.where(PendingAction.created_at < until)
    handoff_count = int((await db.execute(handoff_q)).scalar() or 0)

    summary = summarize_outcomes(
        OutcomeCounts(
            enquiries=enquiries,
            answered=answered,
            qualified_leads=qualified,
            deals_attributed=attributed,
            attributed_value_brl=attributed_value,
            human_handoffs=handoff_count,
        ),
        attribution_source="crm_deal.agent_id",
        attribution_confidence="medium",
    )
    summary["avg_first_response_seconds"] = (
        int(sum(first_response_seconds) / len(first_response_seconds))
        if first_response_seconds
        else None
    )
    summary["window_conversations"] = _OUTCOME_WINDOW
    return summary


@router.get("/outcomes")
async def business_outcomes(
    days: int = 0,
    baseline_days: int = 0,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    """Business outcomes, not infrastructure metrics.

    Every count is read from persisted rows. Attribution is reported as
    "a CRM deal linked to an agent", with source and confidence — never as
    proven revenue.

    ``days=0`` keeps the original all-time response shape. With ``days>0`` the
    two windows are compared: the last ``days`` against the ``baseline_days``
    immediately before it. ``comparable`` is false when the baseline has no
    conversations — a delta computed against zero is not a result.
    """
    if days < 1:
        return await _outcome_snapshot(db, org_id)

    now = _utcnow()
    since = now - timedelta(days=days)
    current = await _outcome_snapshot(db, org_id, since=since, until=now)
    response = dict(current)
    response["window"] = {"days": days, "since": since.isoformat(), "until": now.isoformat()}

    if baseline_days > 0:
        prev_since = since - timedelta(days=baseline_days)
        previous = await _outcome_snapshot(
            db, org_id, since=prev_since, until=since
        )
        numeric = (
            "enquiries",
            "answered",
            "unanswered",
            "answered_pct",
            "qualified_leads",
            "qualification_pct",
            "follow_up_completion_pct",
            "deals_attributed",
            "attributed_value_brl",
            "human_handoffs",
            "human_handoff_pct",
            "failure_pct",
            "avg_first_response_seconds",
        )
        delta = {
            key: round(current.get(key) - previous.get(key), 2)
            for key in numeric
            if isinstance(current.get(key), (int, float))
            and isinstance(previous.get(key), (int, float))
        }
        response["previous"] = previous
        response["delta"] = delta
        response["comparable"] = bool(previous.get("enquiries"))
    return response


# ─── Cost per outcome ───

_COST_WINDOW_DAYS = 30


@router.get("/unit-cost")
async def unit_cost(
    days: int = _COST_WINDOW_DAYS,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    """What one conversation and one qualified lead cost to produce.

    Source of truth is ``usage_records``: it is the only table that persists
    both LLM spend and WhatsApp charges. It is written by the usage meter, so a
    deployment where the meter never ran reports zeros — the response says
    ``has_cost_data: false`` instead of presenting zero as a real number.
    """
    from aios.config import settings
    from aios.db.models import CrmDeal, UsageRecord

    now = _utcnow()
    since = now - timedelta(days=days)
    rows = (
        await db.execute(
            select(UsageRecord).where(
                UsageRecord.org_id == org_id,
                UsageRecord.date >= since.date().isoformat(),
            )
        )
    ).scalars().all()

    llm_usd = sum(r.cost_usd or 0 for r in rows)
    wa_usd = sum(getattr(r, "whatsapp_cost_usd", 0) or 0 for r in rows)
    wa_messages = sum(getattr(r, "whatsapp_messages", 0) or 0 for r in rows)
    tokens = sum(r.llm_tokens or 0 for r in rows)
    fx = float(settings.usd_brl_rate or 5.5)
    total_brl = round((llm_usd + wa_usd) * fx, 2)

    conversations = int(
        (
            await db.execute(
                select(func.count(Conversation.id)).where(
                    Conversation.org_id == org_id, Conversation.created_at >= since
                )
            )
        ).scalar()
        or 0
    )
    qualified = int(
        (
            await db.execute(
                select(func.count(CrmDeal.id)).where(
                    CrmDeal.org_id == org_id, CrmDeal.created_at >= since
                )
            )
        ).scalar()
        or 0
    )

    return {
        "window_days": days,
        "since": since.date().isoformat(),
        "totals": {
            "llm_cost_brl": round(llm_usd * fx, 2),
            "whatsapp_cost_brl": round(wa_usd * fx, 2),
            "total_cost_brl": total_brl,
            "llm_tokens": tokens,
            "whatsapp_messages": wa_messages,
        },
        "counts": {"conversations": conversations, "qualified_leads": qualified},
        "cost_per_conversation_brl": (
            round(total_brl / conversations, 2) if conversations else None
        ),
        "cost_per_qualified_lead_brl": (
            round(total_brl / qualified, 2) if qualified else None
        ),
        "fx_usd_brl": fx,
        "has_cost_data": bool(llm_usd or wa_usd),
        "source": "usage_records",
    }


# ─── Telemetry Endpoints ───


@router.get("/telemetry/summary")
async def telemetry_summary(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    """Org-wide telemetry, from flushed rows (same numbers on every replica).

    Reading `telemetry.get_org_summary()` here reported the calling process's
    unflushed dict: the API replica runs no agents, so it usually showed zeros.
    """
    from aios.db.models import AgentMetric

    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(AgentMetric.messages), 0),
                func.coalesce(func.sum(AgentMetric.tokens), 0),
                func.coalesce(func.sum(AgentMetric.errors), 0),
                func.coalesce(
                    func.sum(AgentMetric.avg_response_ms * AgentMetric.samples), 0
                ),
                func.count(func.distinct(AgentMetric.agent_id)),
                func.coalesce(func.sum(AgentMetric.samples), 0),
            ).where(AgentMetric.org_id == org_id)
        )
    ).one()

    messages = int(row[0] or 0)
    errors = int(row[2] or 0)
    samples = int(row[5] or 0)
    return {
        "total_messages": messages,
        "total_tokens": int(row[1] or 0),
        "total_errors": errors,
        "error_rate_pct": round(errors / max(messages, 1) * 100, 1),
        "avg_response_ms": int(row[3] / samples) if samples else 0,
        "active_agents": int(row[4] or 0),
    }


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
async def pgvector_health(
    db: DatabaseBackend = Depends(get_db_backend),
    user=Depends(get_current_user),
):
    try:
        from sqlalchemy import text
        r = await db.execute(text("SELECT 1 FROM pg_extension WHERE extname='vector'"))
        ok = r.scalar() is not None
        return {"ok": ok, "mode": "pgvector" if ok else "BOW fallback"}
    except Exception as e:
        return {"ok": False, "mode": "BOW fallback", "error": str(e)[:120]}

@router.get("/health/evolution-rate/{instance}")
async def evolution_rate(instance: str, user=Depends(get_current_user)):
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


@router.get("/kpi/sales")
async def sales_kpis(
    pipeline: str | None = None,
    baseline_days: int = 30,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    """Authoritative CRM KPIs from deterministic SQL/Python; LLM never decides."""
    stmt = select(CrmDeal.stage, CrmDeal.value, CrmDeal.created_at).where(CrmDeal.org_id == org_id)
    if pipeline:
        stmt = stmt.where(CrmDeal.pipeline == pipeline)
    rows = (await db.execute(stmt)).all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(days=max(1, min(baseline_days, 365)))

    def _metrics(deals):
        won = [d for d in deals if d.stage == "closed_won"]
        lost = [d for d in deals if d.stage == "closed_lost"]
        closed = len(won) + len(lost)
        return {
            "win_rate": win_rate(len(won), len(lost)),
            "close_rate": conversion_rate(closed, len(deals)),
            "average_deal_size": average_deal_size([float(d.value or 0.0) for d in won]),
            "pipeline_deals": float(len(deals)),
        }

    current = _metrics(rows)
    previous = _metrics([r for r in rows if r.created_at and r.created_at < cutoff])
    catalog = kpi_catalog(category="commercial")
    return {
        "pipeline": pipeline or "all",
        "baseline_days": max(1, min(baseline_days, 365)),
        "current": current,
        "previous": previous,
        "interpretation": interpret_kpis(current, previous),
        "measurement": {
            "level": "business/process",
            "category": "commercial",
            "scope": "org",
            "org_id": org_id,
            "catalog_metrics": [m["key"] for m in catalog["metrics"] if m["key"].startswith("crm.")],
            "guardrails": {
                "no_fake_metrics": True,
                "not_a_target_by_itself": "Not a target by itself; use with denominator/context and balancing metrics.",
                "baseline_required_for_target": True,
            },
        },
    }


@router.get("/kpi/catalog")
async def kpi_catalog_endpoint(
    level: str | None = None,
    category: str | None = None,
    user=Depends(get_current_user),
):
    """Measurement taxonomy by level/category. Unknown/not_instrumented explicit."""
    return kpi_catalog(level=level, category=category)


def _safe_count(result) -> int | None:
    try:
        value = result.scalar()
        return int(value or 0)
    except Exception:
        return None


async def _governance_snapshot(db: DatabaseBackend, org_id: str) -> dict:
    from aios.db.models import AuditLog, PendingAction

    audit_count = _safe_count(
        await db.execute(select(func.count(AuditLog.id)).where(AuditLog.org_id == org_id))
    )

    pa_rows = (
        await db.execute(
            select(PendingAction.status, PendingAction.created_at, PendingAction.decided_at)
            .where(PendingAction.org_id == org_id)
        )
    ).all()
    decided = [r for r in pa_rows if r.status in {"approved", "rejected"} and r.created_at and r.decided_at]
    rejected = [r for r in pa_rows if r.status == "rejected"]
    latencies = []
    for r in decided:
        delta = (r.decided_at - r.created_at).total_seconds() / 3600
        if delta >= 0:
            latencies.append(delta)
    approval_latency_hours = round(sum(latencies) / len(latencies), 4) if latencies else (0.0 if decided == [] and any(r.status in {"approved", "rejected"} for r in pa_rows) else None)
    # If there are decided rows but no valid timestamps, keep unknown.
    if decided == [] and any(r.status in {"approved", "rejected"} for r in pa_rows):
        approval_latency_hours = None

    open_incidents = None
    mttr_hours = None
    try:
        from aios.governance.security import SecurityIncident

        inc_rows = (
            await db.execute(
                select(SecurityIncident.status, SecurityIncident.detected_at, SecurityIncident.recovered_at, SecurityIncident.closed_at)
                .where(SecurityIncident.org_id == org_id)
            )
        ).all()
        open_incidents = sum(1 for r in inc_rows if r.status not in {"closed", "recovered"})
        resolved = []
        for r in inc_rows:
            end = r.recovered_at or r.closed_at
            if r.detected_at and end:
                delta = (end - r.detected_at).total_seconds() / 3600
                if delta >= 0:
                    resolved.append(delta)
        mttr_hours = round(sum(resolved) / len(resolved), 4) if resolved else None
    except Exception:
        open_incidents = None
        mttr_hours = None

    open_privacy_requests = None
    privacy_completion_rate = None
    try:
        from aios.governance.privacy import PrivacyRequest

        pr_rows = (
            await db.execute(
                select(PrivacyRequest.status).where(PrivacyRequest.org_id == org_id)
            )
        ).all()
        total = len(pr_rows)
        completed = sum(1 for r in pr_rows if r.status == "completed")
        open_privacy_requests = sum(1 for r in pr_rows if r.status not in {"completed", "rejected"})
        privacy_completion_rate = round(completed / total, 4) if total else None
    except Exception:
        open_privacy_requests = None
        privacy_completion_rate = None

    snapshot = governance_kpis_snapshot(
        audit_count=audit_count,
        decided_approvals=len([r for r in pa_rows if r.status in {"approved", "rejected"}]) if pa_rows is not None else None,
        rejected_approvals=len(rejected),
        approval_latency_hours=approval_latency_hours,
        open_incidents=open_incidents,
        mttr_hours=mttr_hours,
        open_privacy_requests=open_privacy_requests,
        privacy_completion_rate=privacy_completion_rate,
    )
    snapshot["scope"] = "org"
    snapshot["org_id"] = org_id
    snapshot["sources"] = {
        "audit_logs": "available" if audit_count is not None else "unknown",
        "pending_actions": "available",
        "security_incidents": "available" if open_incidents is not None else "unknown",
        "privacy_requests": "available" if open_privacy_requests is not None else "unknown",
    }
    return snapshot


@router.get("/kpi/governance")
async def governance_kpis(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    """Governance KPI category. Missing/unwired metrics reported as unknown/partial."""
    return await _governance_snapshot(db, org_id)


@router.post("/kpi/targets/validate")
async def validate_kpi_target(
    payload: dict,
    user=Depends(get_current_user),
):
    """Validate target proposal. No persistence in this endpoint; use POST /kpi/targets to persist."""
    result = validate_target_proposal(
        metric_key=str(payload.get("metric_key") or ""),
        target_value=payload.get("target_value"),
        baseline_value=payload.get("baseline_value"),
        baseline_window_days=payload.get("baseline_window_days"),
        evidence=payload.get("evidence"),
        owner=payload.get("owner"),
        balancing_metrics=payload.get("balancing_metrics") or [],
    )
    result["persistence"] = {
        "persisted": False,
        "mode": "org_extra_data",
        "schema_table": None,
        "blocker": "Validation-only endpoint; use POST /api/analytics/kpi/targets for durable org_extra_data persistence.",
    }
    return result


@router.get("/kpi/targets")
async def list_kpi_targets_endpoint(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    """List persisted KPI targets from Organization.extra_data (no schema table)."""
    org = await db.get(Organization, org_id)
    return list_kpi_targets(org.extra_data if org else {})


@router.post("/kpi/targets")
async def set_kpi_target_endpoint(
    payload: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    user=Depends(get_current_user),
    org_id: str = Depends(get_org_id),
):
    """Persist KPI target in Organization.extra_data. Fail closed on validation/guardrail errors."""
    from fastapi import HTTPException

    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Organization not found")

    result = set_kpi_target(
        extra_data=org.extra_data if isinstance(org.extra_data, dict) else {},
        metric_key=str(payload.get("metric_key") or ""),
        target_value=payload.get("target_value"),
        baseline_value=payload.get("baseline_value"),
        baseline_window_days=payload.get("baseline_window_days"),
        evidence=payload.get("evidence"),
        owner=payload.get("owner"),
        balancing_metrics=payload.get("balancing_metrics") or [],
        actor_user_id=user.id,
        actor_org_id=org_id,
    )
    if not result.get("ok"):
        raise HTTPException(422, {"message": "KPI target rejected (fail closed)", **result})

    org.extra_data = result["extra_data"]
    await db.commit()
    await db.refresh(org)
    stored = list_kpi_targets(org.extra_data)
    target = result["target"]
    return {
        "ok": True,
        "persistence": result["persistence"],
        "target": target,
        "targets": stored["targets"],
        "count": stored["count"],
        "guardrails": result["guardrails"],
    }
