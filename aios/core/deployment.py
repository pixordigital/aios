"""Verified deployment and real readiness.

`Agent.status == "active"` used to be the whole deployment: a DB flag flipped by
either the API or the dashboard. Nothing proved the agent could answer, the two
routes diverged, and the API recorded a success before its "health check" had
run. This module is now the only writer that turns a flag into evidence:

- the agent's configured model/provider must answer a real request
- every configured tool must still load
- the result is persisted on AgentInstance.extra_data, so it survives restarts
  and is identical in every gunicorn worker

The probe deliberately skips AgentRuntime.run(): that writes conversation and
message rows, records telemetry and mutates the health tracker, so deploying an
agent would fabricate the very traffic used to judge it. It calls the same
provider object the runtime uses, with no tools attached (tools are validated by
ToolEngine construction instead of executing side effects during a deploy).
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from aios.config import PLANS, settings
from aios.core.audit import log_audit
from aios.db.models import AgentInstance, Organization

logger = logging.getLogger(__name__)

PROBE_PROMPT = "Reply with exactly: OK"
PROBE_MAX_TOKENS = 16
# Deploy probes spend a real provider call inside a web request. Two concurrent
# probes are enough to verify a fleet; unlimited ones would let any authenticated
# user tie up the (2) gunicorn workers with slow model calls.
_PROBE_SLOTS = asyncio.Semaphore(2)


class DeploymentError(Exception):
    """Base for deploy failures that are safe to show to the caller."""

    status_code = 422


class AgentNotReady(DeploymentError):
    status_code = 422


class AgentStopped(DeploymentError):
    status_code = 409


class QuotaExceeded(DeploymentError):
    status_code = 403


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(error) -> str:
    return str(error).replace("\n", " ")[:400]


def _static_checks(agent) -> None:
    """Fail before spending a provider call on an agent that cannot run."""
    llm = agent.llm_config or {}
    if not (llm.get("model") or "").strip():
        raise AgentNotReady("llm_config.model is not set")
    if not (agent.system_prompt or "").strip():
        raise AgentNotReady("system_prompt is empty")

    from aios.core.tools import ToolEngine

    engine = ToolEngine(agent.tools or [], org_id=agent.org_id or "", agent_id=agent.id)
    if engine.missing:
        raise AgentNotReady("tools unavailable: " + ", ".join(sorted(engine.missing)))

    gov = agent.governance_config or {}
    denied = set(gov.get("denied_tools") or [])
    blocked = sorted(denied.intersection(agent.tools or []))
    if blocked:
        raise AgentNotReady("tools denied by governance but still configured: " + ", ".join(blocked))
    allowed = gov.get("allowed_tools", "__all__")
    if allowed != "__all__":
        outside = sorted(set(agent.tools or []).difference(allowed))
        if outside:
            raise AgentNotReady("tools outside the governance allow-list: " + ", ".join(outside))


async def probe_agent(agent, timeout: float | None = None) -> dict:
    """Prove the agent's model/provider answers. Raises AgentNotReady on failure.

    Monkeypatched by the test suite: tests must never call a paid provider.
    """
    _static_checks(agent)

    from aios.core.agent import AgentRuntime

    timeout = settings.deploy_probe_timeout_seconds if timeout is None else timeout
    runtime = AgentRuntime(agent)
    model = (agent.llm_config or {}).get("model", "openai/gpt-4o")
    started = time.monotonic()
    try:
        async with _PROBE_SLOTS:
            response = await asyncio.wait_for(
                runtime.llm.chat_retry(
                    messages=[
                        {"role": "system", "content": agent.system_prompt},
                        {"role": "user", "content": PROBE_PROMPT},
                    ],
                    model=model,
                    temperature=0,
                    max_tokens=PROBE_MAX_TOKENS,
                ),
                timeout=timeout,
            )
    except asyncio.TimeoutError:
        raise AgentNotReady(f"provider did not answer within {timeout:g}s")
    except Exception as exc:  # provider errors are the point of the probe
        raise AgentNotReady(f"provider call failed: {_clean(exc)}")

    content = (response or {}).get("content") or ""
    if not content.strip():
        raise AgentNotReady("provider returned an empty response")

    return {
        "model": model,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "reply": content.strip()[:120],
    }


async def _enforce_quota(db, agent, org_id: str) -> None:
    if settings.internal_mode:
        return
    org = await db.get(Organization, org_id)
    plan = ((org.extra_data or {}).get("plan", "free") if org else "free")
    if plan not in ("unlimited",):
        limits = PLANS.get(plan, PLANS["free"])
        max_agents: int = limits.get("max_agents", 2)
        from sqlalchemy import func

        from aios.db.models import Agent

        count = (
            await db.execute(
                select(func.count(Agent.id)).where(
                    Agent.org_id == org_id, Agent.status == "active"
                )
            )
        ).scalar() or 0
        if count >= max_agents and agent.status != "active":
            raise QuotaExceeded(f"quota max_agents {max_agents} for {plan}")


async def deploy_and_verify(db, agent, org_id: str, user_id: str | None = None) -> dict:
    """Deploy only if the agent answers. Returns a small result dict.

    A failed re-deploy of an already-active agent keeps the previous running
    version and the active status: one bad canary must not take down the version
    that is working.
    """
    from aios.core.agent_health import health_tracker

    if not health_tracker.is_available(agent.id):
        raise AgentStopped(f"agent {agent.name} circuit breaker open (stopped). Reset health first.")

    await _enforce_quota(db, agent, org_id)

    was_active = agent.status == "active"
    deploy_colour = "green" if was_active else "blue"
    try:
        evidence = await probe_agent(agent)
    except Exception as exc:
        failed = AgentInstance(
            agent_id=agent.id,
            org_id=org_id,
            status="failed",
            extra_data={
                "deploy": deploy_colour,
                "verified": False,
                "failed_at": _now(),
                "deployed_by": user_id,
                "error": _clean(exc),
            },
        )
        db.add(failed)
        if not was_active:
            agent.status = "draft"
        await log_audit(
            db,
            org_id,
            "agent.deploy_failed",
            "agent",
            user_id=user_id,
            resource_id=agent.id,
            details={"name": agent.name, "error": _clean(exc), "previous_active": was_active},
        )
        await db.commit()
        raise AgentNotReady(str(exc)) from exc

    if not was_active:
        agent.status = "active"
    instance = AgentInstance(
        agent_id=agent.id,
        org_id=org_id,
        status="running",
        extra_data={
            "deploy": deploy_colour,
            "canary": was_active,
            "verified": True,
            "verified_at": _now(),
            "deployed_at": _now(),
            "deployed_by": user_id,
            **evidence,
        },
    )
    db.add(instance)
    await log_audit(
        db,
        org_id,
        "agent.deploy",
        "agent",
        user_id=user_id,
        resource_id=agent.id,
        details={
            "name": agent.name,
            "blue_green": deploy_colour,
            "verified": True,
            "model": evidence["model"],
            "latency_ms": evidence["latency_ms"],
        },
    )
    await db.commit()
    await db.refresh(agent)
    return {"agent": agent, "instance": instance, "evidence": evidence}


async def verify_agent(db, agent, org_id: str, user_id: str | None = None) -> dict:
    """Re-probe and record a new evidence row without changing deployment state.

    A new row (rather than mutating the latest running instance) matters when
    the last canary failed: the failed attempt stays in history, and the
    verification of the version actually serving becomes the newest record.

    A failed re-verify also gets a row (verified=False) so the dashboard stops
    showing an old green result as if it were current; the agent keeps running.
    """
    try:
        evidence = await probe_agent(agent)
    except Exception as exc:
        db.add(
            AgentInstance(
                agent_id=agent.id,
                org_id=org_id,
                status="failed",
                extra_data={
                    "deploy": "verify",
                    "canary": False,
                    "verified": False,
                    "failed_at": _now(),
                    "deployed_by": user_id,
                    "error": _clean(exc),
                },
            )
        )
        await log_audit(
            db,
            org_id,
            "agent.verify_failed",
            "agent",
            user_id=user_id,
            resource_id=agent.id,
            details={"name": agent.name, "error": _clean(exc)},
        )
        await db.commit()
        raise
    instance = AgentInstance(
        agent_id=agent.id,
        org_id=org_id,
        status="running",
        extra_data={
            "deploy": "verify",
            "canary": False,
            "verified": True,
            "verified_at": _now(),
            "deployed_by": user_id,
            **evidence,
        },
    )
    db.add(instance)
    await log_audit(
        db,
        org_id,
        "agent.verify",
        "agent",
        user_id=user_id,
        resource_id=agent.id,
        details={"name": agent.name, "model": evidence["model"], "latency_ms": evidence["latency_ms"]},
    )
    await db.commit()
    return {"agent": agent, "instance": instance, "evidence": evidence}


def _instance_view(inst) -> dict:
    if inst is None:
        return {"result": "none", "at": None, "model": None, "latency_ms": None,
                "error": None, "deploy": None, "status": None}
    ev = inst.extra_data or {}
    verified = ev.get("verified")
    result = "verified" if verified is True else "failed" if verified is False else "unverified"
    at = ev.get("verified_at") or ev.get("failed_at")
    if at is None and inst.created_at is not None:
        at = inst.created_at.isoformat()
    return {
        "result": result,
        "at": at,
        "model": ev.get("model"),
        "latency_ms": ev.get("latency_ms"),
        "error": ev.get("error"),
        "deploy": ev.get("deploy"),
        "status": inst.status,
    }


def deployment_view(agent, latest=None, history=None) -> dict:
    """Template/API view of deployment truth. `latest` is the newest instance."""
    current = _instance_view(latest)
    if agent.status == "active":
        state = {
            "verified": "verified",
            "failed": "failed_active",
        }.get(current["result"], "unverified")
    else:
        state = "failed" if current["result"] == "failed" else "draft"
    return {
        "state": state,
        **current,
        "history": [_instance_view(i) for i in (history or [])],
    }


async def latest_instances(db, org_id: str, agent_ids: list[str]) -> dict[str, AgentInstance]:
    """Latest AgentInstance per agent, one query, ordered for deterministic picks."""
    if not agent_ids:
        return {}
    rows = (
        await db.execute(
            select(AgentInstance)
            .where(
                AgentInstance.org_id == org_id,
                AgentInstance.agent_id.in_(agent_ids),
            )
            .order_by(AgentInstance.created_at.desc())
        )
    ).scalars().all()
    latest: dict[str, AgentInstance] = {}
    for row in rows:
        latest.setdefault(row.agent_id, row)
    return latest


async def migration_state() -> str:
    """'ok', 'unversioned' or 'behind:<applied>-><head>'."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from sqlalchemy import text

        from aios.db.engine import async_session

        root = Path(__file__).resolve().parents[2]
        head = ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_current_head()
        async with async_session() as db:
            try:
                applied = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            except Exception:
                return "unversioned"
        if not applied:
            return "unversioned"
        return "ok" if applied == head else f"behind:{applied}->{head}"
    except Exception as exc:
        return f"unknown:{_clean(exc)}"


async def redis_state() -> str:
    try:
        from aios.tasks.queue import get_redis_pool

        pool = await get_redis_pool()
        if hasattr(pool, "ping"):
            await pool.ping()
        return "ok"
    except Exception:
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(settings.redis_url or "redis://localhost:6379")
            await client.ping()
            await client.close()
            return "ok"
        except Exception:
            return "fallback"


async def system_status(db_ok: bool) -> dict:
    """Deploy readiness shown to operators and returned by /health/ready."""
    return {
        "db": "ok" if db_ok else "down",
        "migrations": await migration_state(),
        "redis": await redis_state(),
    }
