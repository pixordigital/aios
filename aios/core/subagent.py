"""Isolated subagents — subprocess-based parallel execution.

Parent spawns child via multiprocessing. Zero context cost.
Child runs independently, returns JSON result.
"""

import asyncio
import json
import logging
import multiprocessing
import time
from dataclasses import dataclass, field

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


class SubAgentPool:
    """Manage subprocess-based subagents."""

    def __init__(self, max_concurrent: int = 5):
        self._max = max_concurrent
        self._active: dict[str, multiprocessing.Process] = {}
        self._results: dict[str, SubagentResult] = {}

    async def spawn(self, agent_config: dict, task_prompt: str,
                    timeout: float = 120.0) -> SubagentResult:
        """Spawn a single subagent. Blocks until done or timeout."""
        import uuid
        task_id = str(uuid.uuid4())[:8]

        queue = multiprocessing.Queue()
        p = multiprocessing.Process(
            target=_subagent_worker,
            args=(task_id, agent_config, task_prompt, queue),
            daemon=True,
        )
        self._active[task_id] = p
        p.start()

        result = SubagentResult(task_id=task_id, status="running")
        self._results[task_id] = result

        start = time.time()
        p.join(timeout=timeout)

        if p.is_alive():
            p.terminate()
            p.join(timeout=5)
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
        self._active.pop(task_id, None)
        return result

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
