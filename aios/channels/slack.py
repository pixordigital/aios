"""Slack channel — Events API inbound (webhook) + Web API outbound.

Inbound arrives via POST /api/slack/webhook. Outbound is lazy: the Bolt app is
built on first send, so a ChannelConnection that was never started at boot can
still deliver.
"""

import logging

from aios.channels.base import Channel, OutboundMessage

logger = logging.getLogger(__name__)


class SlackChannel(Channel):
    channel_type = "slack"

    def __init__(self, connection=None, agent_or_team=None, db=None):
        self.connection = connection
        self.agent_or_team = agent_or_team
        self.db = db
        self._config = connection.config if connection else {}
        self._app = None

    async def _ensure_app(self):
        """Build the Bolt app on first use.

        delivery.py calls build() per send, which returns a fresh instance — so
        start() at boot never reaches the object that actually delivers. Lazy
        init is the fix; same pattern as the Evolution channel.
        """
        if self._app is not None:
            return self._app
        token = self._config.get("bot_token")
        if not token:
            logger.warning("Slack send skipped: bot_token not configured")
            return None
        from slack_bolt.async_app import AsyncApp
        self._app = AsyncApp(token=token)
        return self._app

    def _resolve_channel(self, message: OutboundMessage) -> str:
        """Inbound stores the Slack channel as 'channel_id'; older callers used 'channel'."""
        extra = message.extra_data or {}
        return (
            extra.get("channel_id")
            or extra.get("channel")
            or self._config.get("default_channel")
            or ""
        )

    async def send(self, message: OutboundMessage) -> str | None:
        channel = self._resolve_channel(message)
        if not channel:
            logger.warning("Slack send skipped: no channel in extra_data or config")
            return None
        app = await self._ensure_app()
        if not app:
            return None
        try:
            resp = await app.client.chat_postMessage(channel=channel, text=message.text)
        except Exception:
            # slack_bolt raises SlackApiError; surface it so delivery can retry
            logger.exception("Slack chat_postMessage failed for channel %s", channel)
            raise
        return resp.get("ts") if resp else None

    async def start(self) -> None:
        await self._ensure_app()

    async def stop(self) -> None:
        self._app = None
