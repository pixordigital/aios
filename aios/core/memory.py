"""Memory manager — working buffer + DB persistence."""

import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aios.db.models import Message

logger = logging.getLogger(__name__)


class MemoryManager:
    """Agent memory: working buffer in-memory, loaded from DB on init.

    ponytail: in-memory buffer per agent. PGVector/chroma when >1000 memories.
    """

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        # conversation_id → list of {role, content}
        self._buffers: dict[str, list[dict]] = defaultdict(list)
        self._loaded: set[str] = set()

    async def add(self, conversation_id: str, role: str, content: str) -> None:
        if not content:
            return
        self._buffers[conversation_id].append({"role": role, "content": content})
        # ponytail: keep last 50 messages per conversation
        if len(self._buffers[conversation_id]) > 50:
            self._buffers[conversation_id].pop(0)

    async def get_recent(self, conversation_id: str, limit: int = 20, db: AsyncSession | None = None) -> list[dict]:
        # lazy-load from DB on first access (survives restarts)
        if conversation_id not in self._loaded and db is not None:
            await self._load_from_db(conversation_id, db)
        return self._buffers.get(conversation_id, [])[-limit:]

    async def _load_from_db(self, conversation_id: str, db: AsyncSession) -> None:
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .limit(50)
        )
        for msg in result.scalars().all():
            self._buffers[conversation_id].append({
                "role": msg.role,
                "content": msg.content,
            })
        self._loaded.add(conversation_id)

    async def search_relevant(self, query: str, top_k: int = 5) -> list[str]:
        """Stub — returns empty. Wire vector search when DB supports it."""
        return []

    async def clear(self, conversation_id: str) -> None:
        self._buffers.pop(conversation_id, None)
        self._loaded.discard(conversation_id)
