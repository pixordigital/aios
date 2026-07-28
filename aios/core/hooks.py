"""Hook system — plugin points at every kernel boundary.

Pattern: register callbacks at named hooks, kernel fires them.
Enables analytics, audit, rate-limiting, and custom middleware
without modifying kernel code.

ponytail: synchronous hooks only. Async when hook chains need I/O.
"""

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class HookPoint(Enum):
    # LLM calls
    BEFORE_LLM_CALL = "before_llm_call"
    AFTER_LLM_CALL = "after_llm_call"
    # Tool execution
    BEFORE_TOOL_EXEC = "before_tool_exec"
    AFTER_TOOL_EXEC = "after_tool_exec"
    # Memory
    BEFORE_MEMORY_READ = "before_memory_read"
    AFTER_MEMORY_READ = "after_memory_read"
    BEFORE_MEMORY_WRITE = "before_memory_write"
    AFTER_MEMORY_WRITE = "after_memory_write"
    # Agent lifecycle
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    AGENT_ERROR = "agent_error"
    # Scheduler
    AGENT_QUEUED = "agent_queued"
    AGENT_DEQUEUED = "agent_dequeued"
    AGENT_PREEMPTED = "agent_preempted"
    # System
    ON_ERROR = "on_error"


@dataclass
class HookContext:
    """Mutable context passed through hook chain. Hooks can modify it."""
    trace_id: str = ""
    agent_id: str = ""
    conversation_id: str = ""
    data: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def add_error(self, msg: str):
        self.errors.append(msg)


HookFn = Callable[[HookContext], None]


class HookRegistry:
    """In-process hook registry. One per kernel instance."""

    def __init__(self):
        self._hooks: dict[HookPoint, list[HookFn]] = defaultdict(list)

    def register(self, point: HookPoint, fn: HookFn) -> None:
        self._hooks[point].append(fn)
        logger.debug("Hook registered at %s: %s", point.value, fn.__name__)

    def unregister(self, point: HookPoint, fn: HookFn) -> None:
        self._hooks[point] = [h for h in self._hooks[point] if h is not fn]

    def fire(self, point: HookPoint, ctx: HookContext | None = None) -> HookContext:
        """Fire all hooks at a point. Returns context (mutated by hooks)."""
        if ctx is None:
            ctx = HookContext()
        for fn in self._hooks.get(point, []):
            try:
                fn(ctx)
            except Exception:
                logger.exception("Hook %s failed at %s", fn.__name__, point.value)
        return ctx

    def clear(self) -> None:
        self._hooks.clear()


# Global hook registry
hooks = HookRegistry()
