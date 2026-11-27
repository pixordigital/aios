"""Isolated subagents — subprocess-based parallel execution.

Parent spawns child via multiprocessing. Zero context cost.
Child runs independently, returns JSON result.
"""

import asyncio
import json
import logging
import multiprocessing
import multiprocessing.process
import os
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SubagentResult:
    task_id: str
    status: str  # running|completed|failed|timeout
    output: str = ""
    error: str = ""
    duration_ms: int = 0


def _subagent_worker(task_id: str, agent_config: dict, task_prompt: str,
                     result_queue: multiprocessing.Queue):
    """Run in subprocess — loads agent, executes task, puts JSON result."""
    try:
        from aios.db.models import Agent as AgentModel
        from aios.core.agent import AgentRuntime

        # Reconstruct agent model from config
        agent = AgentModel(
            id=agent_config["id"],
            name=agent_config.get("name", "subagent"),
            agent_type=agent_config.get("agent_type", "custom"),
            llm_config=agent_config.get("llm_config", {}),
            system_prompt=agent_config.get("system_prompt", ""),
            tools=agent_config.get("tools", []),
            memory_config=agent_config.get("memory_config", {}),
            governance_config=agent_config.get("governance_config", {}),
            org_id=agent_config.get("org_id", ""),
        )

        runtime = AgentRuntime(agent)

        async def _run():
            conv_id = f"subagent:{task_id}"
            collected = ""
            async for event in runtime.run_stream(conv_id, task_prompt):
                if event["type"] == "token":
                    collected += event.get("content", "")
                elif event["type"] == "error":
                    return json.dumps({"status": "failed", "error": event.get("error", "")})
            return json.dumps({"status": "completed", "output": collected})

        result = asyncio.run(_run())
        result_queue.put(result)
    except Exception as e:
        logger.exception("Subagent worker failed: %s", task_id)
        result_queue.put(json.dumps({"status": "failed", "error": str(e)[:500]}))


def _subagent_audit(action: str, details: dict) -> None:
    try:
        from aios.core.audit_sink import append as _audit_append

        _audit_append(str(details.get("org_id") or "system"), action, {"component": "subagent", **details})
    except Exception:
        logger.debug("subagent audit failed action=%s", action, exc_info=True)


class SubagentSpawnError(RuntimeError):
    pass


class SubAgentPool:
    """Manage subprocess-based subagents."""

    def __init__(self, max_concurrent: int = 5):
        self._max = max_concurrent
        self._active: dict[str, multiprocessing.process.BaseProcess] = {}
        self._results: dict[str, SubagentResult] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)

    @staticmethod
    def _enabled() -> bool:
        raw = os.getenv("AIOS_SUBAGENT_SPAWN_ENABLED")
        if raw is not None:
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        try:
            from aios.config import settings

            return bool(getattr(settings, "subagent_spawn_enabled", True))
        except Exception:
            return True

    async def _check_quota(self, agent_config: dict) -> None:
        org_id = str(agent_config.get("org_id") or "")
        if not org_id:
            raise SubagentSpawnError("subagent spawn denied: missing org_id")
        try:
            from aios.core.limits import check_org_limits
            from aios.db.backend import db_session

            async with db_session() as db:
                allowed, reason = await check_org_limits(org_id, db)
            if not allowed:
                raise SubagentSpawnError(f"subagent spawn denied: {reason}")
        except SubagentSpawnError:
            raise
        except Exception as exc:
            # fail closed on quota/policy check errors
            raise SubagentSpawnError(f"subagent spawn quota check failed: {exc}") from exc

    async def spawn(self, agent_config: dict, task_prompt: str,
                    timeout: float = 120.0) -> SubagentResult:
        """Spawn a single subagent. Blocks until done or timeout."""
        import uuid
        task_id = str(uuid.uuid4())[:8]
        org_id = str(agent_config.get("org_id") or "")
        agent_id = str(agent_config.get("id") or "")
        base_details = {"task_id": task_id, "org_id": org_id, "agent_id": agent_id}
        if not self._enabled():
            _subagent_audit("subagent.spawn.blocked", {**base_details, "reason": "disabled"})
            raise SubagentSpawnError("subagent spawn disabled (AIOS_SUBAGENT_SPAWN_ENABLED=false)")
        if len(self._active) >= self._max:
            _subagent_audit("subagent.spawn.blocked", {**base_details, "reason": "max_concurrent"})
            raise SubagentSpawnError("subagent spawn denied: max concurrent limit reached")
        await self._check_quota(agent_config)

        queue: multiprocessing.Queue = multiprocessing.Queue()
        # spawn, not fork: a forked child inherits this process's live asyncio
        # loop and the module-level SQLAlchemy engine/connection pool, then
        # calls asyncio.run() on top of it. Reusing an inherited pool across
        # fork corrupts it in both directions. spawn re-imports clean.
        ctx = multiprocessing.get_context("spawn")
        p = ctx.Process(
            target=_subagent_worker,
            args=(task_id, agent_config, task_prompt, queue),
            daemon=True,
        )
        _subagent_audit("subagent.spawn.requested", {**base_details, "timeout": timeout})
        await self._semaphore.acquire()
        try:
            self._active[task_id] = p
            p.start()

            result = SubagentResult(task_id=task_id, status="running")
            self._results[task_id] = result

            start = time.time()
            # Off the event loop: a synchronous join parked the whole ARQ worker
            # for up to `timeout` seconds, so no other inbound message was served
            # and no websocket heartbeat fired while one subagent ran.
            await asyncio.to_thread(p.join, timeout)

            if p.is_alive():
                p.terminate()
                await asyncio.to_thread(p.join, 5)
                result.status = "timeout"
                result.error = f"Subagent timed out after {timeout}s"
            elif not queue.empty():
                raw = queue.get_nowait()
                parsed = json.loads(raw)
                result.status = parsed.get("status", "completed")
                result.output = parsed.get("output", "")
                result.error = parsed.get("error", "")
            else:
                result.status = "failed"
                result.error = "Subagent produced no output"

            result.duration_ms = int((time.time() - start) * 1000)
            _subagent_audit(
                "subagent.spawn.completed" if result.status == "completed" else "subagent.spawn.failed",
                {**base_details, "status": result.status, "duration_ms": result.duration_ms},
            )
            return result
        finally:
            self._active.pop(task_id, None)
            self._semaphore.release()

    async def spawn_many(self, tasks: list[dict]) -> list[SubagentResult]:
        """Spawn multiple subagents concurrently.

        tasks: [{"agent_config": {...}, "prompt": "..."}]
        """
        coros = [
            self.spawn(t["agent_config"], t["prompt"])
            for t in tasks[:self._max]
        ]
        return await asyncio.gather(*coros)

    def active_count(self) -> int:
        return len(self._active)

    def get_result(self, task_id: str) -> SubagentResult | None:
        return self._results.get(task_id)


# Global instance
subagent_pool = SubAgentPool()
