"""Async event bus — decouples channel ingestion from agent processing.

Pattern: channels publish InboundEvent → worker pool processes →
response published back to channel's response topic.

ponytail: single-process asyncio. Upgrade to Redis pub/sub
when horizontal scaling required.
"""

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class InboundEvent:
    channel_connection_id: str
    conversation_id: str
    text: str
    user_id: str = ""
    extra_data: dict = field(default_factory=dict)


@dataclass
class OutboundEvent:
    channel_connection_id: str
    conversation_id: str
    text: str
    extra_data: dict = field(default_factory=dict)


class EventBus:
    """Async event bus with publish/subscribe and worker pool."""

    def __init__(self, max_workers: int = 10):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._handlers: dict[str, list[Callable[[InboundEvent], Awaitable[None]]]] = defaultdict(list)
        self._workers: list[asyncio.Task] = []
        self._max_workers = max_workers
        self._running = False

    def subscribe(self, channel_type: str, handler: Callable[[InboundEvent], Awaitable[None]]) -> None:
        self._handlers[channel_type].append(handler)
        logger.info("Handler registered for channel type: %s", channel_type)

    async def publish(self, event: InboundEvent, channel_type: str = "") -> bool:
        """Queue event for processing. Returns False if queue full."""
        event_key = channel_type or event.channel_connection_id
        try:
            self._queue.put_nowait((event_key, event))
            return True
        except asyncio.QueueFull:
            logger.warning("Event bus queue full, dropping event for %s", event_key)
            return False

    async def start(self) -> None:
        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(i))
            for i in range(self._max_workers)
        ]
        logger.info("Event bus started with %d workers", self._max_workers)

    async def stop(self) -> None:
        self._running = False
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("Event bus stopped")

    async def _worker(self, idx: int) -> None:
        while self._running:
            try:
                event_key, event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            handlers = self._handlers.get(event_key, []) + self._handlers.get("*", [])
            if not handlers:
                logger.debug("No handler for event key: %s", event_key)
                continue

            for handler in handlers:
                try:
                    await handler(event)
                except Exception:
                    logger.exception("Handler failed for event key: %s", event_key)


# Global bus instance
event_bus = EventBus()
