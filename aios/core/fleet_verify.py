"""Fleet verification — background, org-scoped, survives the browser.

Verifying 13-15 agents one by one in a request is slow enough that operators
close the tab. This runs in the ARQ worker, writes progress to Redis after every
agent, and the dashboard re-attaches to the same state on reload. The in-process
fallback keeps single-node/dev installs working; it is explicitly marked in the
state instead of pretending the job is durable.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from aios.config import settings
from aios.db.backend import db_session
from aios.db.models import Agent
from aios.core.deployment import verify_agent
from aios.tasks.queue import enqueue_task, get_redis_pool

logger = logging.getLogger(__name__)

STATE_TTL_SECONDS = 86_400
LOCK_TTL_SECONDS = 900
ACTIVE_STATUSES = {"queued", "running", "cancelling"}

_MEM: dict[str, dict] = {}
_LOCKS: set[str] = set()
_TASKS: set[asyncio.Task] = set()


class FleetVerifyError(Exception):
    pass


def _key(org_id: str) -> str:
    return f"aios:fleet_verify:{org_id}"


def _lock_key(org_id: str) -> str:
    return f"aios:fleet_verify:lock:{org_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _redis():
    try:
        return await get_redis_pool()
    except Exception:
        return None


async def _acquire_lock(org_id: str) -> bool:
    pool = await _redis()
    if pool is not None:
        try:
            return bool(await pool.set(_lock_key(org_id), "1", nx=True, ex=LOCK_TTL_SECONDS))
        except Exception:
            logger.warning("fleet verify: redis lock unavailable, using process lock", exc_info=True)
    if org_id in _LOCKS:
        return False
    _LOCKS.add(org_id)
    return True


async def _release_lock(org_id: str) -> None:
    _LOCKS.discard(org_id)
    pool = await _redis()
    if pool is not None:
        try:
            await pool.delete(_lock_key(org_id))
        except Exception:
            logger.warning("fleet verify: could not release redis lock", exc_info=True)


async def _save(state: dict) -> None:
    _MEM[state["org_id"]] = state
    pool = await _redis()
    if pool is not None:
        try:
            await pool.set(_key(state["org_id"]), json.dumps(state), ex=STATE_TTL_SECONDS)
        except Exception:
            logger.warning("fleet verify: redis state write failed", exc_info=True)


async def get_fleet_state(org_id: str) -> dict | None:
    pool = await _redis()
    if pool is not None:
        try:
            raw = await pool.get(_key(org_id))
            if raw:
                state = json.loads(raw)
                if isinstance(state, dict):
                    return state
        except Exception:
            logger.warning("fleet verify: redis state read failed", exc_info=True)
    state = _MEM.get(org_id)
    if state and state.get("finished_at"):
        try:
            finished = datetime.fromisoformat(state["finished_at"])
            if datetime.now(timezone.utc) - finished > timedelta(seconds=STATE_TTL_SECONDS):
                _MEM.pop(org_id, None)
                return None
        except ValueError:
            pass
    return state


async def start_fleet_verification(db, org_id: str, user_id: str | None = None) -> dict:
    """Queue one fleet verification per org. Idempotent while one is running."""
    if not await _acquire_lock(org_id):
        current = await get_fleet_state(org_id)
        if current and current.get("status") in ACTIVE_STATUSES:
            return current
        # Another process holds the lock with no live state: a previous job may
        # have died. Do not delete its lock (it could still be starting) — the
        # lock TTL expires with the job timeout.
        raise FleetVerifyError("fleet verification is already starting")

    agents = (
        await db.execute(
            select(Agent)
            .where(Agent.org_id == org_id, Agent.status == "active")
            .order_by(Agent.name)
        )
    ).scalars().all()
    if not agents:
        await _release_lock(org_id)
        raise FleetVerifyError("no active agents to verify")

    payload = {"org_id": org_id, "agent_ids": [a.id for a in agents], "user_id": user_id}
    state = {
        "org_id": org_id,
        "job_id": None,
        "status": "queued",
        "runner": "redis",
        "total": len(agents),
        "done": 0,
        "ok": 0,
        "failed": 0,
        "started_at": _now(),
        "finished_at": None,
        "cancel_requested": False,
        "results": [],
    }
    await _save(state)

    job = await enqueue_task(
        "aios.tasks.jobs.verify_fleet_job",
        payload,
        _job_timeout=900,
    )
    if job is None:
        # No Redis: run in this process so a single-node install still works.
        # Marked so the UI does not promise durability across a restart.
        state["runner"] = "in-process"
        await _save(state)
        task = asyncio.create_task(run_fleet_verification(payload))
        # Keep a reference: the loop holds tasks weakly and could GC a running one.
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)
    else:
        state["job_id"] = getattr(job, "job_id", None)
        await _save(state)
    return state


async def cancel_fleet_verification(org_id: str) -> dict | None:
    state = await get_fleet_state(org_id)
    if not state or state.get("status") not in ACTIVE_STATUSES:
        return state
    state["cancel_requested"] = True
    if state.get("status") == "running":
        state["status"] = "cancelling"
    await _save(state)
    return state


async def run_fleet_verification(payload: dict) -> dict:
    """ARQ job body (also used by the in-process fallback)."""
    org_id = payload["org_id"]
    agent_ids = payload.get("agent_ids") or []
    user_id = payload.get("user_id")
    state = await get_fleet_state(org_id) or {
        "org_id": org_id, "job_id": None, "status": "queued", "runner": "redis",
        "total": len(agent_ids), "done": 0, "ok": 0, "failed": 0,
        "started_at": _now(), "finished_at": None, "cancel_requested": False,
        "results": [],
    }
    state.update({"status": "running", "started_at": state.get("started_at") or _now()})
    await _save(state)

    semaphore = asyncio.Semaphore(max(1, settings.fleet_verify_concurrency))
    # One job per org (enforced by the lock), so a per-run lock is enough and
    # avoids a module-level asyncio.Lock bound to a previous event loop.
    state_lock = asyncio.Lock()

    async def _one(agent_id: str) -> None:
        async with semaphore:
            current = await get_fleet_state(org_id) or {}
            if current.get("cancel_requested"):
                return
            name = agent_id[:8]
            entry = {"agent_id": agent_id, "name": name, "ok": False,
                     "model": None, "latency_ms": None, "error": None}
            try:
                async with db_session() as db:
                    agent = await db.get(Agent, agent_id)
                    if not agent or agent.org_id != org_id:
                        raise FleetVerifyError("agent not found in this org")
                    name = agent.name
                    result = await verify_agent(db, agent, org_id, user_id=user_id)
                entry.update({
                    "name": name,
                    "ok": True,
                    "model": result["evidence"].get("model"),
                    "latency_ms": result["evidence"].get("latency_ms"),
                })
            except Exception as exc:
                logger.warning("fleet verify: agent %s failed: %s", agent_id, exc)
                entry.update({"name": name, "error": str(exc)[:300]})

            async with state_lock:
                fresh = await get_fleet_state(org_id) or state
                fresh.setdefault("results", []).append(entry)
                fresh["done"] = len(fresh["results"])
                fresh["ok"] = sum(1 for r in fresh["results"] if r.get("ok"))
                fresh["failed"] = fresh["done"] - fresh["ok"]
                await _save(fresh)

    try:
        await asyncio.gather(*(_one(aid) for aid in agent_ids))
    except Exception:
        logger.exception("fleet verify crashed for org %s", org_id)
    finally:
        fresh = await get_fleet_state(org_id) or state
        fresh["done"] = len(fresh.get("results", []))
        fresh["ok"] = sum(1 for r in fresh["results"] if r.get("ok"))
        fresh["failed"] = fresh["done"] - fresh["ok"]
        fresh["status"] = "cancelled" if fresh.get("cancel_requested") else "done"
        fresh["finished_at"] = _now()
        await _save(fresh)
        await _release_lock(org_id)
    return fresh
