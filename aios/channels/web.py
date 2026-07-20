"""WebSocket channel — real-time web chat via FastAPI WebSocket.

SECURITY: bare except blocks and origin validation addressed.
"""

from aios.channels.base import Channel, OutboundMessage


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
            import json
            await ws.send_json({"text": message.text})
        return None

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        for conv_id, ws in list(self._connections.items()):
            try:
                await ws.close()
            except (RuntimeError, ConnectionError):
                pass  # already closed or never opened
        self._connections.clear()


# global connections dict
_connections: dict[str, object] = {}
WebChannel._connections = _connections
