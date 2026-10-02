"""Agent message bus — typed pub/sub for agent-to-agent communication.

Enables structured conversations between agents within a team.
No external broker — in-process asyncio event bus.
"""

import asyncio
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


@dataclass
class AgentMessage:
    """A typed message between agents."""
    type: str  # e.g. "analysis", "question", "report", "error"
    sender: str
    recipient: str | None  # None = broadcast to all subscribers
    payload: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    correlation_id: str = ""  # threads messages together


class MessageBus:
    """In-process pub/sub bus for agent messages.

    ponytail: single process bus. Swap for Redis pub/sub when
    agents run in separate processes.
    """

    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._history: list[AgentMessage] = []
        self._max_history = 100

    def subscribe(self, message_type: str) -> asyncio.Queue:
        """Return a queue that receives messages of this type."""
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers[message_type].append(q)
        return q

    def unsubscribe(self, message_type: str, q: asyncio.Queue) -> None:
        self._subscribers[message_type] = [s for s in self._subscribers[message_type] if s is not q]

    async def publish(self, msg: AgentMessage) -> int:
        """Publish message to all subscribers of its type. Returns delivery count."""
        self._history.append(msg)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        delivered = 0
        for q in self._subscribers.get(msg.type, []):
            try:
                q.put_nowait(msg)
                delivered += 1
            except asyncio.QueueFull:
                pass
        # Also deliver to "*" wildcard subscribers
        for q in self._subscribers.get("*", []):
            try:
                q.put_nowait(msg)
                delivered += 1
            except asyncio.QueueFull:
                pass
        return delivered

    def recent(self, limit: int = 10) -> list[AgentMessage]:
        return self._history[-limit:]

    async def request(
        self,
        msg: AgentMessage,
        timeout: float = 10.0,
    ) -> AsyncGenerator[AgentMessage, None]:
        """Publish and collect responses from subscribers.

        Yields responses until timeout. Each subscriber gets the message;
        they can reply via bus with the same correlation_id.
        """
        msg.correlation_id = msg.correlation_id or uuid.uuid4().hex[:12]
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers[msg.type].append(q)

        await self.publish(msg)

        try:
            while True:
                reply = await asyncio.wait_for(q.get(), timeout=timeout)
                if reply.correlation_id == msg.correlation_id:
                    yield reply
        except asyncio.TimeoutError:
            pass
        finally:
            self.unsubscribe(msg.type, q)


# Global bus instance
bus = MessageBus()
