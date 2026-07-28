"""WebSocket channel — real-time web chat via FastAPI WebSocket.

Supports both inbound (receive) and outbound (send) messages.
Event-driven: incoming messages dispatch to ARQ worker.
"""

import json
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
        ws = self._connections.get(message.conversation_id)
        if ws:
            await ws.send_json({"type": "message", "text": message.text})
        return None

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
            user_id="web_user",
            extra_data={"source": "websocket"},
        )


# global connections dict
_connections: dict[str, object] = {}
WebChannel._connections = _connections
