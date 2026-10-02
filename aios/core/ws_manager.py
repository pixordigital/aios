"""In-process WebSocket fan-out for live agent activity.

Clients are registered as ``(ws, org_id)`` pairs. Delivery is org-scoped: an
event carrying ``org_id`` reaches only clients of that org. An event *without*
``org_id`` is dropped rather than broadcast — it cannot be attributed to a
tenant, and the old blanket fan-out was a cross-tenant leak. Every emitter
therefore has to supply ``org_id``; ``approval_requested`` does so explicitly.

``broadcast()`` is synchronous and only enqueues, because the hook registry
(``aios.core.hooks``) fires synchronously and the canvas hooks into it. The
consumer is owned by ``aios.core.agent_events``, which also handles
cross-process delivery via redis.

ponytail: in-process queue + optional redis bridge. The single queue exists so
lifecycle events (sync hooks) and stream events (async generators) share one
delivery path and one org filter. If delivery ever needs per-client state
beyond org_id, replace the tuple with a small dataclass here.
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Bound the queue so a canvas client that never reads cannot grow memory
# without limit. Dropping the newest event is the right trade: the next
# lifecycle event re-syncs node state.
MAX_QUEUE = 2000


class WSManager:
    def __init__(self) -> None:
        self._clients: set[tuple[Any, str | None]] = set()
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=MAX_QUEUE)

    # ── client registry ──────────────────────────────────────────────

    def register(self, ws: Any, org_id: str | None = None) -> None:
        self._clients.add((ws, org_id))

    def unregister(self, ws: Any, org_id: str | None = None) -> None:
        self._clients.discard((ws, org_id))

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # ── producer (sync-safe) ──────────────────────────────────────────

    @property
    def queue(self) -> "asyncio.Queue[dict]":
        return self._queue

    def broadcast(self, data: dict) -> None:
        """Enqueue an event for delivery. Never blocks, never raises.

        Called from the synchronous hook registry, so it must not await.
        """
        try:
            self._queue.put_nowait(data)
        except asyncio.QueueFull:
            logger.debug("ws queue full, dropping event %s", data.get("type"))

    # ── consumer (async) ──────────────────────────────────────────────

    async def _deliver_local(self, data: dict) -> None:
        """The one delivery point. Org filter lives here and nowhere else.

        Called by both the local pump and the redis subscriber so neither can
        bypass the tenant check.
        """
        org = data.get("org_id")
        if not org:
            # Fail closed. An event we cannot attribute to a tenant must not be
            # guessed at: every emitter degrades to "" when the agent or hook
            # context carries no org, and broadcasting those would hand one
            # tenant's agent activity, streamed text and conversation ids to
            # every other tenant's canvas.
            logger.warning(
                "ws: dropping org-less event %s — cannot scope to a tenant", data.get("type")
            )
            return
        dead: list[tuple[Any, str | None]] = []
        for ws, org_id in list(self._clients):
            if org != org_id:
                continue
            try:
                await ws.send_json(data)
            except Exception:
                dead.append((ws, org_id))
        for entry in dead:
            self._clients.discard(entry)


ws_manager = WSManager()
