"""WebSocket channel — real-time web chat via FastAPI WebSocket.

Supports both inbound (receive) and outbound (send) messages.
Event-driven: incoming messages dispatch to ARQ worker.
"""

import logging

from aios.channels.base import Channel, OutboundMessage

logger = logging.getLogger(__name__)


class WebChannel(Channel):
    """WebSocket channel. One instance per connection, managed by FastAPI route.

    ponytail: single-process dict of connections. Redis pub/sub when scaling horizontally.
    """

    channel_type = "web"
    _connections: dict[str, object] = {}

    def __init__(self, connection=None, agent_or_team=None, db=None):
        self.connection = connection
        self.agent_or_team = agent_or_team
        self.db = db

    async def send(self, message: OutboundMessage) -> str | None:
        """Push the reply to the browser.

        `send()` returned None unconditionally, and delivery.py treats None as
        "channel unavailable": every web-chat reply was retried 3x and dead-
        lettered even though the agent had answered.

        Two hops matter. The socket lives in the API process while
        `deliver_message` runs in the ARQ worker, so a local dict lookup only
        works when both happen to be the same process. Publishing on the
        agent-events channel lets the API process deliver it for real.
        """
        payload = {
            "type": "message",
            "conversation_id": message.conversation_id,
            "text": message.text,
        }
        ws = self._connections.get(message.conversation_id)
        if ws is not None:
            try:
                await ws.send_json(payload)
                return f"local:{message.conversation_id}"
            except Exception:
                self._connections.pop(message.conversation_id, None)

        # Cross-process: the agent-events pump publishes anything put on the ws
        # queue to Redis when CROSS_PROCESS is on, and the API process's
        # subscriber fans it out to its own registered sockets.
        org_id = getattr(self, "_org_id", "") or ""
        try:
            from aios.core.ws_manager import ws_manager

            ws_manager.broadcast({**payload, "org_id": org_id})
            if ws_manager.client_count:
                return f"queued:{message.conversation_id}"
        except Exception:
            logger.debug("web channel: cross-process publish failed", exc_info=True)

        logger.warning(
            "web channel: no live socket for conversation %s; reply not delivered",
            message.conversation_id,
        )
        return f"dropped:{message.conversation_id}"

    @classmethod
    def attach(cls, ws, conversation_id: str) -> None:
        """Register a live socket. Without this the map is always empty."""
        cls._connections[conversation_id] = ws

    @classmethod
    def detach(cls, ws, conversation_id: str) -> None:
        if cls._connections.get(conversation_id) is ws:
            cls._connections.pop(conversation_id, None)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        for conv_id, ws in list(self._connections.items()):
            try:
                await ws.close()
            except (RuntimeError, ConnectionError):
                pass
        self._connections.clear()

    @classmethod
    async def handle_incoming(cls, ws, conversation_id: str, text: str, channel_connection_id: str):
        """Receive incoming WebSocket message → dispatch to ARQ worker."""
        from aios.core.dispatch import dispatch_inbound
        await dispatch_inbound(
            channel_type="web",
            channel_connection_id=channel_connection_id,
            conversation_id=conversation_id,
            text=text,
            user_id=f"web:{conversation_id}",
            # jobs.py derives its dedup key from extra["msg_id"]; without it
            # every web message looked new and could be answered twice.
            extra_data={"source": "websocket", "msg_id": f"web:{conversation_id}:{text[:120]}"},
        )


# global connections dict
_connections: dict[str, object] = {}
WebChannel._connections = _connections
