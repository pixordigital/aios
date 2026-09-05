"""Usage tracking and plan limit enforcement per org."""

import logging
from datetime import date

from sqlalchemy import func, select

from aios.config import PLANS, DEFAULT_PLAN
from aios.db.models import Agent, Organization, Team, UsageRecord

logger = logging.getLogger(__name__)


def _get_plan(org: Organization) -> str:
    return (org.extra_data or {}).get("plan", DEFAULT_PLAN)


def _plan_limit(org: Organization, key: str):
    plan_name = _get_plan(org)
    limits = PLANS.get(plan_name, PLANS[DEFAULT_PLAN])
    return limits.get(key)


async def check_org_limits(org_id: str, db) -> tuple[bool, str]:
    """Check if org can execute another agent run. Returns (allowed, reason)."""
    org = await db.get(Organization, org_id)
    if not org:
        return False, "Organization not found"

    if not org.is_active:
        return False, "Organization is suspended"

    if (org.extra_data or {}).get("unlimited"):
        return True, ""

    plan_name = _get_plan(org)
    limits = PLANS.get(plan_name, PLANS[DEFAULT_PLAN])

    # agent count check
    max_agents = limits.get("max_agents", 999)
    if max_agents != 999:
        count = (await db.execute(select(func.count(Agent.id)).where(Agent.org_id == org_id, Agent.status == "active"))).scalar() or 0
        if count >= max_agents:
            return False, f"Plan limit: max {max_agents} active agents ({plan_name} plan)"

    # team count check
    max_teams = limits.get("max_teams", 999)
    if max_teams != 999:
        count = (await db.execute(select(func.count(Team.id)).where(Team.org_id == org_id))).scalar() or 0
        if count >= max_teams:
            return False, f"Plan limit: max {max_teams} teams ({plan_name} plan)"

    # daily message check
    today = date.today().isoformat()
    max_msgs = limits.get("max_messages_per_day", 99999)
    if max_msgs != 99999:
        record = (await db.execute(
            select(UsageRecord).where(UsageRecord.org_id == org_id, UsageRecord.date == today)
        )).scalar_one_or_none()
        if record and record.messages >= max_msgs:
            return False, f"Daily message limit reached ({max_msgs}/{plan_name} plan)"

    # monthly token check
    max_tokens = limits.get("max_tokens_per_month", 999999999)
    if max_tokens != 999999999:
        from sqlalchemy import extract as _extract
        import datetime as _dt
        now = _dt.date.today()
        start_month = now.replace(day=1).isoformat()
        q = select(func.coalesce(func.sum(UsageRecord.llm_tokens), 0)).where(UsageRecord.org_id == org_id, UsageRecord.date >= start_month)
        total = (await db.execute(q)).scalar() or 0
        if total >= max_tokens:
            return False, f"Monthly token limit reached ({max_tokens}/{plan_name} plan)"

    return True, ""


async def track_usage(org_id: str, db, messages: int = 1, tokens: int = 0, llm_calls: int = 1, cost_usd: float = 0.0):
    today = date.today().isoformat()
    record = (
        await db.execute(select(UsageRecord).where(UsageRecord.org_id == org_id, UsageRecord.date == today))
    ).scalar_one_or_none()

    if record:
        record.messages += messages
        record.llm_tokens += tokens
        record.llm_calls += llm_calls
        record.cost_usd = (record.cost_usd or 0) + cost_usd
    else:
        db.add(
            UsageRecord(
                org_id=org_id,
                date=today,
                messages=messages,
                llm_tokens=tokens,
                llm_calls=llm_calls,
                cost_usd=cost_usd,
            )
        )
    await db.commit()
    try:
        if cost_usd:
            from prometheus_client import Counter as _PC

            _PC("aios_cost_usd_total", "cost").inc(cost_usd)
    except Exception:
        pass


async def get_usage_summary(org_id: str, db) -> dict:
    today = date.today().isoformat()
    record = (
        await db.execute(select(UsageRecord).where(UsageRecord.org_id == org_id, UsageRecord.date == today))
    ).scalar_one_or_none()
    return {
        "messages_today": record.messages if record else 0,
        "llm_calls_today": record.llm_calls if record else 0,
        "tokens_today": record.llm_tokens if record else 0,
        "cost_today": round(record.cost_usd if record and record.cost_usd else 0, 4),
    }


async def get_monthly_usage(org_id: str, db) -> dict:
    import datetime as _dt
    from datetime import timedelta

    today = _dt.date.today()
    start_month = today.replace(day=1).isoformat()
    end_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1).isoformat()
    days_in_month = (int(end_month[:4]), int(end_month[5:7]))
    import calendar

    days_in_month_num = calendar.monthrange(today.year, today.month)[1]
    day_of_month = today.day

    records = (await db.execute(select(UsageRecord).where(UsageRecord.org_id == org_id, UsageRecord.date >= start_month))).scalars().all()
    total_tokens = sum(r.llm_tokens for r in records)
    total_messages = sum(r.messages for r in records)
    total_calls = sum(r.llm_calls for r in records)
    total_cost = sum(r.cost_usd or 0 for r in records)
    avg_daily_cost = total_cost / max(day_of_month, 1)
    forecast_cost = avg_daily_cost * days_in_month_num
    forecast_tokens = (total_tokens / max(day_of_month, 1)) * days_in_month_num if day_of_month else 0

    org = await db.get(Organization, org_id)
    plan_name = (org.extra_data or {}).get("plan", DEFAULT_PLAN) if org else DEFAULT_PLAN
    limits = PLANS.get(plan_name, PLANS[DEFAULT_PLAN])
    max_tokens = limits.get("max_tokens_per_month", 999999999)
    max_msgs_day = limits.get("max_messages_per_day", 99999)
    pct_tokens = round(total_tokens / max_tokens * 100, 1) if max_tokens and max_tokens != 999999999 else 0
    pct_cost_vs_plan = pct_tokens

    # billing cycle info
    remaining_days = days_in_month_num - day_of_month
    next_billing = (today.replace(day=1) + timedelta(days=days_in_month_num)).isoformat()

    # build daily series for chart
    daily_series = [{"date": r.date, "tokens": r.llm_tokens, "cost": round(r.cost_usd or 0, 4), "messages": r.messages} for r in sorted(records, key=lambda x: x.date)]

    # status
    status = "ok"
    if pct_tokens >= 90:
        status = "critical"
    elif pct_tokens >= 75:
        status = "warning"
    elif pct_tokens >= 50:
        status = "attention"

    return {
        "period": f"{start_month} → {today.isoformat()}",
        "next_billing": next_billing,
        "remaining_days": remaining_days,
        "days_in_month": days_in_month_num,
        "day_of_month": day_of_month,
        "plan": plan_name,
        "max_tokens": max_tokens,
        "max_msgs_day": max_msgs_day,
        "total_tokens": total_tokens,
        "total_messages": total_messages,
        "total_calls": total_calls,
        "total_cost": round(total_cost, 4),
        "avg_daily_cost": round(avg_daily_cost, 4),
        "avg_daily_tokens": int(total_tokens / max(day_of_month, 1)) if day_of_month else 0,
        "forecast_cost": round(forecast_cost, 4),
        "forecast_tokens": int(forecast_tokens),
        "pct_tokens": pct_tokens,
        "pct_cost_vs_plan": pct_cost_vs_plan,
        "status": status,
        "daily_series": daily_series,
        "will_exceed": forecast_tokens > max_tokens if max_tokens != 999999999 else False,
        "days_until_pay": remaining_days,
        "cost_today": round(records[-1].cost_usd if records and records[-1].date == today.isoformat() else 0, 4) if records else 0,
    }


async def get_agent_usage_breakdown(org_id: str, db) -> list[dict]:
    from aios.db.models import AgentMetric
    import datetime as _dt

    today = _dt.date.today()
    start_month = today.replace(day=1).isoformat().replace("-", "-")[:7]  # YYYY-MM
    # fetch metrics for current month prefix match on hour (YYYY-MM-DD-HH)
    q = select(AgentMetric).where(AgentMetric.org_id == org_id, AgentMetric.hour >= start_month)
    rows = (await db.execute(q)).scalars().all()
    agg: dict[str, dict] = {}
    for r in rows:
        agg.setdefault(r.agent_id, {"agent_id": r.agent_id, "tokens": 0, "messages": 0, "cost": 0, "calls": 0})
        agg[r.agent_id]["tokens"] += r.tokens
        agg[r.agent_id]["messages"] += r.messages
        # cost estimate per agent: use tracing default
        from aios.core.tracing import estimate_cost

        agg[r.agent_id]["cost"] += estimate_cost("openai/gpt-4o-mini", r.tokens)
        agg[r.agent_id]["calls"] += r.messages
    # enrich names
    if agg:
        agent_ids = list(agg.keys())
        agents = (await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))).scalars().all()
        name_map = {a.id: a.name for a in agents}
        for aid, v in agg.items():
            v["name"] = name_map.get(aid, aid[:8])
            v["cost"] = round(v["cost"], 4)
    return sorted(agg.values(), key=lambda x: x["tokens"], reverse=True)
