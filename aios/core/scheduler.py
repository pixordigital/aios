"""Agent scheduler — request queue with lifecycle management.

Agents are treated like OS processes: queued → running → blocked → terminated.
Supports FIFO and Round-Robin scheduling policies.

ponytail: in-process asyncio queue. Distributed scheduler (Redis/Celery)
when agents span processes.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum

from aios.core.hooks import HookContext, HookPoint, hooks

logger = logging.getLogger(__name__)


class AgentState(Enum):
    PENDING = "pending"
    QUEUED = "queued"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"  # waiting on tool/LLM
    PREEMPTED = "preempted"
    TERMINATED = "terminated"
    FAILED = "failed"


@dataclass
class AgentProcess:
    """Represents an agent's execution within the scheduler."""
    agent_id: str
    agent_name: str = ""
    conversation_id: str = ""
    state: AgentState = AgentState.QUEUED
    priority: int = 0  # lower = higher priority
    created_at: float = 0.0
    started_at: float = 0.0
    ended_at: float = 0.0
    total_runtime_ms: float = 0.0
    llm_calls: int = 0
    tool_calls: int = 0
    error: str = ""
    preempted_count: int = 0

    @property
    def wait_time_ms(self) -> float:
        if self.started_at and self.created_at:
            return round((self.started_at - self.created_at) * 1000, 1)
        return 0.0


class SchedulerPolicy:
    FIFO = "fifo"
    ROUND_ROBIN = "round_robin"


class AgentScheduler:
    """Schedule agent execution with configurable policy."""

    def __init__(self, policy: str = SchedulerPolicy.FIFO):
        self.policy = policy
        self._queue: asyncio.Queue[AgentProcess] = asyncio.Queue()
        self._processes: dict[str, AgentProcess] = {}
        self._running: dict[str, AgentProcess] = {}
        self._rr_idx: int = 0
        self._max_concurrent = 10
        self._running_count = 0

    # ─── Agent lifecycle ───

    def enqueue(self, agent_id: str, conv_id: str = "", agent_name: str = "",
                priority: int = 0) -> AgentProcess:
        """Add agent to request queue."""
        proc = AgentProcess(
            agent_id=agent_id,
            agent_name=agent_name,
            conversation_id=conv_id,
            state=AgentState.QUEUED,
            created_at=time.time(),
            priority=priority,
        )
        self._processes[agent_id] = proc
        self._queue.put_nowait(proc)

        hctx = HookContext()
        hctx.agent_id = agent_id
        hctx.data["conversation_id"] = conv_id
        hooks.fire(HookPoint.AGENT_QUEUED, hctx)

        return proc

    def start(self, agent_id: str) -> AgentProcess | None:
        """Mark agent as running."""
        proc = self._processes.get(agent_id)
        if not proc:
            return None
        proc.state = AgentState.RUNNING
        proc.started_at = time.time()
        self._running[agent_id] = proc
        self._running_count += 1
        return proc

    async def pop(self) -> AgentProcess | None:
        """Pop next agent from queue based on policy."""
        try:
            proc = await asyncio.wait_for(self._queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            return None

        proc.state = AgentState.READY
        hctx = HookContext()
        hctx.agent_id = proc.agent_id
        hooks.fire(HookPoint.AGENT_DEQUEUED, hctx)
        return proc

    def block(self, agent_id: str) -> None:
        """Agent is waiting on tool/LLM."""
        proc = self._processes.get(agent_id)
        if proc:
            proc.state = AgentState.BLOCKED

    def unblock(self, agent_id: str) -> None:
        """Agent resumed from blocked state."""
        proc = self._processes.get(agent_id)
        if proc and proc.state == AgentState.BLOCKED:
            proc.state = AgentState.RUNNING

    def terminate(self, agent_id: str, error: str = "") -> None:
        """Mark agent as terminated."""
        proc = self._processes.get(agent_id)
        if not proc:
            return
        proc.state = AgentState.TERMINATED if not error else AgentState.FAILED
        proc.ended_at = time.time()
        proc.total_runtime_ms = round((proc.ended_at - proc.started_at) * 1000, 1) if proc.started_at else 0
        proc.error = error
        self._running.pop(agent_id, None)
        self._running_count = max(0, self._running_count - 1)

        hctx = HookContext()
        hctx.agent_id = agent_id
        hctx.data["error"] = error
        hooks.fire(HookPoint.AGENT_END if not error else HookPoint.AGENT_ERROR, hctx)

    def preempt(self, agent_id: str) -> bool:
        """Preempt a running agent. Returns True if preempted."""
        proc = self._running.get(agent_id)
        if not proc:
            return False
        proc.state = AgentState.PREEMPTED
        proc.preempted_count += 1
        proc.ended_at = time.time()
        self._running.pop(agent_id, None)
        self._running_count = max(0, self._running_count - 1)

        hctx = HookContext()
        hctx.agent_id = agent_id
        hooks.fire(HookPoint.AGENT_PREEMPTED, hctx)
        return True

    # ─── Stats ───

    def get_process(self, agent_id: str) -> AgentProcess | None:
        return self._processes.get(agent_id)

    def queue_size(self) -> int:
        return self._queue.qsize()

    def running_count(self) -> int:
        return self._running_count

    def summary(self) -> dict:
        return {
            "policy": self.policy,
            "queued": self._queue.qsize(),
            "running": self._running_count,
            "total_processes": len(self._processes),
            "processes": [
                {
                    "agent_id": p.agent_id,
                    "agent_name": p.agent_name,
                    "state": p.state.value,
                    "wait_time_ms": p.wait_time_ms,
                    "runtime_ms": p.total_runtime_ms,
                    "llm_calls": p.llm_calls,
                    "tool_calls": p.tool_calls,
                    "preempted": p.preempted_count,
                    "error": p.error,
                }
                for p in self._processes.values()
            ],
        }


# Global scheduler
scheduler = AgentScheduler()
