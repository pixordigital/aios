"""Syscall layer — typed dispatch for agent→kernel interactions.

Every agent call goes through kernel.syscall() instead of calling
providers/memory/tools directly. Enables interception, tracing,
rate-limiting, and hook firing at a single point.

ponytail: in-process dispatch. Remote syscalls (RPC/gRPC) when
agents run in separate processes.
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from aios.core.hooks import HookContext, HookPoint, hooks

logger = logging.getLogger(__name__)


class SyscallType(Enum):
    LLM_CHAT = "llm.chat"
    LLM_CHAT_STREAM = "llm.chat_stream"
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    MEMORY_MERGE = "memory.merge"
    MEMORY_CLEAR = "memory.clear"
    TOOL_EXEC = "tool.execute"
    TOOL_SCHEMA = "tool.schema"
    STORAGE_SAVE = "storage.save"
    STORAGE_READ = "storage.read"
    STORAGE_LIST = "storage.list"
    AGENT_RUN = "agent.run"
    AGENT_RUN_STRUCTURED = "agent.run_structured"
    AGENT_CONTEXT_BUILD = "agent.context_build"


@dataclass
class SyscallRequest:
    """Request envelope — what an agent sends to the kernel."""
    type: SyscallType
    params: dict = field(default_factory=dict)
    trace_id: str = ""
    agent_id: str = ""
    conversation_id: str = ""


@dataclass
class SyscallResponse:
    """Response envelope — what kernel returns to agent."""
    ok: bool = True
    data: Any = None
    error: str = ""


class SyscallError(Exception):
    """Raised by syscall handlers on non-recoverable errors."""
    pass


# Type for handler functions
SyscallHandler = callable  # (SyscallRequest) -> SyscallResponse | Any


class SyscallDispatcher:
    """Dispatch typed syscalls to registered handlers."""

    def __init__(self):
        self._handlers: dict[SyscallType, SyscallHandler] = {}

    def register(self, stype: SyscallType, handler: SyscallHandler) -> None:
        self._handlers[stype] = handler
        logger.debug("Syscall handler registered: %s", stype.value)

    async def dispatch(self, req: SyscallRequest, **extra) -> SyscallResponse:
        """Dispatch a syscall. Fires hooks before and after."""
        handler = self._handlers.get(req.type)
        if not handler:
            return SyscallResponse(ok=False, error=f"No handler for syscall: {req.type.value}")

        # Build hook context
        hctx = HookContext(
            trace_id=req.trace_id,
            agent_id=req.agent_id,
            conversation_id=req.conversation_id,
        )

        # Fire before hook
        hctx.data["syscall"] = req.type.value
        hooks.fire(HookPoint.BEFORE_LLM_CALL, hctx)

        try:
            result = await handler(req, **extra)
            if isinstance(result, SyscallResponse):
                resp = result
            else:
                resp = SyscallResponse(ok=True, data=result)
        except SyscallError as e:
            resp = SyscallResponse(ok=False, error=str(e))
            hctx.add_error(str(e))
        except Exception as e:
            logger.exception("Syscall %s failed", req.type.value)
            resp = SyscallResponse(ok=False, error=str(e))
            hctx.add_error(str(e))

        # Fire after hook
        hctx.data["response"] = resp
        hooks.fire(HookPoint.AFTER_LLM_CALL, hctx)

        return resp


# Global dispatcher
dispatcher = SyscallDispatcher()
