"""Agent health tracker — monitors failures, auto-disables, escalates.

Tracks per-agent error rates. When threshold exceeded:
1. Mark agent as "degraded"
2. If persistent, mark as "stopped"
3. Notify admin via audit log
"""

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_FAILURE_THRESHOLD = 5  # failures before degraded
_STOP_THRESHOLD = 15  # failures before stopped
_FAILURE_WINDOW = 300  # 5 minutes
_RECOVERY_THRESHOLD = 3  # successes to recover from degraded


@dataclass
class AgentHealth:
    agent_id: str
    failures: int = 0
    successes: int = 0
    last_failure: float = 0.0
    last_success: float = 0.0
    status: str = "healthy"  # healthy | degraded | stopped
    consecutive_failures: int = 0


class AgentHealthTracker:
    """Track health status of all agents."""

    def __init__(self):
        self._agents: dict[str, AgentHealth] = {}

    def _get(self, agent_id: str) -> AgentHealth:
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentHealth(agent_id=agent_id)
        return self._agents[agent_id]

    def record_failure(self, agent_id: str, error: str = "") -> str:
        """Record agent failure. Returns new status."""
        h = self._get(agent_id)
        now = time.time()

        # reset if outside window
        if now - h.last_failure > _FAILURE_WINDOW:
            h.consecutive_failures = 0

        h.failures += 1
        h.consecutive_failures += 1
        h.last_failure = now

        old_status = h.status

        if h.consecutive_failures >= _STOP_THRESHOLD:
            h.status = "stopped"
            if old_status != "stopped":
                logger.error("Agent %s STOPPED after %d consecutive failures", agent_id, h.consecutive_failures)
                _escalate(agent_id, "stopped", h.consecutive_failures, error)
        elif h.consecutive_failures >= _FAILURE_THRESHOLD:
            h.status = "degraded"
            if old_status == "healthy":
                logger.warning("Agent %s DEGRADED after %d failures", agent_id, h.consecutive_failures)
                _escalate(agent_id, "degraded", h.consecutive_failures, error)

        return h.status

    def record_success(self, agent_id: str) -> str:
        """Record agent success. Returns new status."""
        h = self._get(agent_id)
        h.successes += 1
        h.last_success = time.time()

        if h.status == "degraded":
            h.consecutive_failures = 0
            if h.successes >= _RECOVERY_THRESHOLD:
                h.status = "healthy"
                logger.info("Agent %s recovered to healthy", agent_id)
        elif h.status == "stopped":
            # don't auto-recover from stopped — requires manual reset
            pass

        return h.status

    def is_available(self, agent_id: str) -> bool:
        """Check if agent is available for processing."""
        h = self._get(agent_id)
        return h.status != "stopped"

    def get_status(self, agent_id: str) -> dict:
        h = self._get(agent_id)
        return {
            "agent_id": agent_id,
            "status": h.status,
            "failures": h.failures,
            "successes": h.successes,
            "consecutive_failures": h.consecutive_failures,
        }

    def reset(self, agent_id: str):
        """Manually reset agent health."""
        self._agents[agent_id] = AgentHealth(agent_id=agent_id, status="healthy")
        logger.info("Agent %s health reset to healthy", agent_id)

    def all_status(self) -> dict:
        return {aid: self.get_status(aid) for aid in self._agents}


def _escalate(agent_id: str, status: str, failure_count: int, error: str):
    """Escalate agent failure to admin via audit log."""
    try:
        import asyncio
        from aios.db.backend import db_session
        from aios.db.models import Agent

        async def _log():
            async with db_session() as db:
                agent = await db.get(Agent, agent_id)
                if agent:
                    from aios.core.audit import log_audit
                    await log_audit(
                        db, agent.org_id, f"agent.{status}", "agent",
                        resource_id=agent_id,
                        details={"failures": failure_count, "error": error[:200]},
                    )

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_log())
        except RuntimeError:
            asyncio.run(_log())
    except Exception:
        logger.exception("Failed to escalate agent %s health", agent_id)


# Global tracker
health_tracker = AgentHealthTracker()
