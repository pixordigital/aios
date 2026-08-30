"""Usage tracking and plan limit enforcement per org."""

import logging
from datetime import date

from sqlalchemy import func, select

from aios.config import PLANS, DEFAULT_PLAN
from aios.db.models import Agent, Organization, Team, UsageRecord

logger = logging.getLogger(__name__)


def _get_plan(org: Organization) -> str:
    return org.extra_data.get("plan", DEFAULT_PLAN)


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

    # unlimited orgs bypass all limits
    if org.extra_data.get("unlimited"):
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


async def track_usage(org_id: str, db, messages: int = 1, tokens: int = 0, llm_calls: int = 1):
    """Increment daily usage counter for org."""
    today = date.today().isoformat()
    record = (await db.execute(
        select(UsageRecord).where(UsageRecord.org_id == org_id, UsageRecord.date == today)
    )).scalar_one_or_none()

    if record:
        record.messages += messages
        record.llm_tokens += tokens
        record.llm_calls += llm_calls
    else:
        db.add(UsageRecord(
            org_id=org_id, date=today,
            messages=messages, llm_tokens=tokens, llm_calls=llm_calls,
        ))
    await db.commit()


async def get_usage_summary(org_id: str, db) -> dict:
    """Return usage stats for dashboard display."""
    today = date.today().isoformat()
    record = (await db.execute(
        select(UsageRecord).where(UsageRecord.org_id == org_id, UsageRecord.date == today)
    )).scalar_one_or_none()
    return {
        "messages_today": record.messages if record else 0,
        "llm_calls_today": record.llm_calls if record else 0,
        "tokens_today": record.llm_tokens if record else 0,
    }
