"""Team orchestration — route messages to agents by strategy."""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from aios.core.agent import AgentRuntime
from aios.db.models import Team

logger = logging.getLogger(__name__)


class TeamOrchestrator:
    """Route incoming messages to the right agent based on strategy."""

    def __init__(self, team, agents: list, db_session_factory=None):
        self.team = team
        self.agents = agents
        self.strategy = team.routing_strategy
        self._db = db_session_factory

    async def handle_message(self, conversation_id: str, message: str, db: AsyncSession | None = None) -> str:
        match self.strategy:
            case "supervisor":
                return await self._supervisor_route(conversation_id, message, db)
            case "round_robin":
                return await self._round_robin(conversation_id, message, db)
            case "broadcast":
                return await self._broadcast(conversation_id, message, db)
            case "semantic":
                return await self._semantic_route(conversation_id, message, db)
            case _:
                return await self._round_robin(conversation_id, message, db)

    async def _supervisor_route(self, conv_id: str, msg: str, db: AsyncSession | None = None) -> str:
        if not self.agents:
            return "No agents in team"
        supervisor = AgentRuntime(self.agents[0], self._db)
        return await supervisor.run(conv_id, msg, db)

    async def _round_robin(self, conv_id: str, msg: str, db: AsyncSession | None = None) -> str:
        if not self.agents:
            return "No agents in team"

        # persisted round-robin: stored in team.extra_data
        extra = dict(self.team.extra_data or {})
        idx = extra.get("_rr_idx", 0)
        extra["_rr_idx"] = (idx + 1) % len(self.agents)
        self.team.extra_data = extra

        if db:
            await db.execute(
                update(Team).where(Team.id == self.team.id).values(extra_data=extra)
            )
            await db.commit()

        agent = AgentRuntime(self.agents[idx], self._db)
        return await agent.run(conv_id, msg, db)

    async def _broadcast(self, conv_id: str, msg: str, db: AsyncSession | None = None) -> str:
        if not self.agents:
            return "No agents in team"
        results = []
        for agent in self.agents:
            loop = AgentRuntime(agent, self._db)
            results.append(await loop.run(conv_id, msg, db))
        best = max(results, key=lambda r: len(r or ""))
        return best or results[0] if results else ""

    async def _semantic_route(self, conv_id: str, msg: str, db: AsyncSession | None = None) -> str:
        # ponytail: falls back to round_robin. Embedding-based routing when vector DB added.
        return await self._round_robin(conv_id, msg, db)
