"""Agent telemetry — tracks per-agent performance metrics.

Records: response time, tokens, errors, tool calls.
Aggregated hourly for dashboard BI.
"""

import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _current_hour() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")


class AgentTelemetry:
    """Track per-agent metrics in-memory, flush to DB periodically."""

    def __init__(self):
        self._metrics: dict[str, dict] = {}  # key: "agent_id:hour" -> metrics

    def record(
        self,
        agent_id: str,
        org_id: str,
        response_ms: int = 0,
        tokens: int = 0,
        error: bool = False,
        tool_calls: int = 0,
    ):
        """Record a metric data point for an agent."""
        hour = _current_hour()
        key = f"{agent_id}:{hour}"

        if key not in self._metrics:
            self._metrics[key] = {
                "agent_id": agent_id,
                "org_id": org_id,
                "hour": hour,
                "messages": 0,
                "tokens": 0,
                "errors": 0,
                "total_response_ms": 0,
                "response_count": 0,
                "tool_calls": 0,
            }

        m = self._metrics[key]
        m["messages"] += 1
        m["tokens"] += tokens
        m["tool_calls"] += tool_calls
        if error:
            m["errors"] += 1
        if response_ms > 0:
            m["total_response_ms"] += response_ms
            m["response_count"] += 1

    def get_metrics_for_agent(self, agent_id: str, hours: int = 24) -> list[dict]:
        """Get recent metrics for an agent."""
        now = datetime.now(timezone.utc)
        cutoff = now.strftime("%Y-%m-%d-%H")
        results = []
        for key, m in self._metrics.items():
            if key.startswith(f"{agent_id}:"):
                avg_ms = m["total_response_ms"] // max(m["response_count"], 1)
                results.append({
                    "hour": m["hour"],
                    "messages": m["messages"],
                    "tokens": m["tokens"],
                    "errors": m["errors"],
                    "avg_response_ms": avg_ms,
                    "tool_calls": m["tool_calls"],
                })
        return sorted(results, key=lambda x: x["hour"])[-hours:]

    def get_org_summary(self, org_id: str) -> dict:
        """Get aggregated metrics for an org."""
        total_messages = 0
        total_tokens = 0
        total_errors = 0
        total_response_ms = 0
        response_count = 0
        agent_count = 0

        seen_agents = set()
        for key, m in self._metrics.items():
            if m["org_id"] == org_id:
                total_messages += m["messages"]
                total_tokens += m["tokens"]
                total_errors += m["errors"]
                total_response_ms += m["total_response_ms"]
                response_count += m["response_count"]
                if m["agent_id"] not in seen_agents:
                    seen_agents.add(m["agent_id"])
                    agent_count += 1

        avg_ms = total_response_ms // max(response_count, 1)
        error_rate = round(total_errors / max(total_messages, 1) * 100, 1)

        return {
            "total_messages": total_messages,
            "total_tokens": total_tokens,
            "total_errors": total_errors,
            "error_rate_pct": error_rate,
            "avg_response_ms": avg_ms,
            "active_agents": agent_count,
        }

    def get_all_agents_summary(self, org_id: str) -> list[dict]:
        """Get per-agent summary for an org."""
        agents = {}
        for key, m in self._metrics.items():
            if m["org_id"] == org_id:
                aid = m["agent_id"]
                if aid not in agents:
                    agents[aid] = {
                        "agent_id": aid,
                        "messages": 0,
                        "tokens": 0,
                        "errors": 0,
                        "total_response_ms": 0,
                        "response_count": 0,
                        "tool_calls": 0,
                    }
                a = agents[aid]
                a["messages"] += m["messages"]
                a["tokens"] += m["tokens"]
                a["errors"] += m["errors"]
                a["total_response_ms"] += m["total_response_ms"]
                a["response_count"] += m["response_count"]
                a["tool_calls"] += m["tool_calls"]

        result = []
        for aid, a in agents.items():
            avg_ms = a["total_response_ms"] // max(a["response_count"], 1)
            error_rate = round(a["errors"] / max(a["messages"], 1) * 100, 1)
            result.append({
                "agent_id": aid,
                "messages": a["messages"],
                "tokens": a["tokens"],
                "errors": a["errors"],
                "error_rate_pct": error_rate,
                "avg_response_ms": avg_ms,
                "tool_calls": a["tool_calls"],
            })
        return sorted(result, key=lambda x: x["messages"], reverse=True)

    async def flush_to_db(self):
        """Write accumulated metrics to DB."""
        if not self._metrics:
            return

        try:
            from aios.db.backend import db_session
            from aios.db.models import AgentMetric
            from sqlalchemy import select

            async with db_session() as db:
                for key, m in list(self._metrics.items()):
                    avg_ms = m["total_response_ms"] // max(m["response_count"], 1)

                    # upsert: update existing or create new
                    existing = (await db.execute(
                        select(AgentMetric).where(
                            AgentMetric.agent_id == m["agent_id"],
                            AgentMetric.hour == m["hour"],
                        )
                    )).scalar_one_or_none()

                    if existing:
                        existing.messages += m["messages"]
                        existing.tokens += m["tokens"]
                        existing.errors += m["errors"]
                        existing.tool_calls += m["tool_calls"]
                        # recalculate avg
                        total_ms = existing.avg_response_ms * (existing.messages - m["messages"]) + m["total_response_ms"]
                        existing.avg_response_ms = total_ms // max(existing.messages, 1)
                    else:
                        db.add(AgentMetric(
                            agent_id=m["agent_id"],
                            org_id=m["org_id"],
                            hour=m["hour"],
                            messages=m["messages"],
                            tokens=m["tokens"],
                            errors=m["errors"],
                            avg_response_ms=avg_ms,
                            tool_calls=m["tool_calls"],
                        ))

                await db.commit()
                logger.info("Flushed %d metric entries to DB", len(self._metrics))
                self._metrics.clear()
        except Exception:
            logger.exception("Failed to flush metrics to DB")


# Global telemetry tracker
telemetry = AgentTelemetry()
