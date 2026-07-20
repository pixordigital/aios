"""Slack Socket Mode channel — Bolt async app."""

from aios.channels.base import Channel, OutboundMessage


class SlackChannel(Channel):
    channel_type = "slack"

    def __init__(self, connection=None, agent_or_team=None, db=None):
        self.connection = connection
        self.agent_or_team = agent_or_team
        self.db = db
        self._config = connection.config if connection else {}
        self._app = None

    async def send(self, message: OutboundMessage) -> str | None:
        if not self._app:
            return None
        channel = message.extra_data.get("channel") if message.extra_data else None
        if not channel:
            return None
        resp = await self._app.client.chat_postMessage(channel=channel, text=message.text)
        return resp.get("ts") if resp else None

    async def start(self) -> None:
        if not self._config.get("bot_token"):
            return
        from slack_bolt.async_app import AsyncApp
        self._app = AsyncApp(token=self._config["bot_token"])
        # ponytail: Socket Mode handler registration deferred

    async def stop(self) -> None:
        self._app = None
