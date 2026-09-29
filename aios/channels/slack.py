"""Slack channel — Events API inbound (webhook) + Web API outbound.

Inbound arrives via POST /api/slack/webhook. Outbound posts directly to the
Web API via httpx (already a dependency) rather than pulling in slack-bolt for
a single chat.postMessage call.
"""

import logging

import httpx

from aios.channels.base import Channel, OutboundMessage

logger = logging.getLogger(__name__)

_API = "https://slack.com/api/chat.postMessage"


class SlackChannel(Channel):
    channel_type = "slack"

    def __init__(self, connection=None, agent_or_team=None, db=None):
        self.connection = connection
        self.agent_or_team = agent_or_team
        self.db = db
        self._config = connection.config if connection else {}
        self._app = None

    def _ensure_app(self):
        """Return the bot token, or None if unconfigured.

        delivery.py calls build() per send, which returns a fresh instance — so
        start() at boot never reaches the object that actually delivers.
        """
        if self._app is not None:
            return self._app
        token = self._config.get("bot_token")
        if not token:
            logger.warning("Slack send skipped: bot_token not configured")
            return None
        self._app = token
        return self._app

    def _resolve_channel(self, message: OutboundMessage) -> str:
        """Inbound stores the Slack channel as 'channel_id'; older callers used 'channel'."""
        extra = message.extra_data or {}
        return (
            extra.get("channel_id")
            or extra.get("channel")
            or self._config.get("slack_channel_id")
            or ""
        )

    async def send(self, message: OutboundMessage) -> str | None:
        channel = self._resolve_channel(message)
        if not channel:
            logger.warning("Slack send skipped: no channel in extra_data or config")
            return None
        token = self._ensure_app()
        if not token:
            return None

        payload = {"channel": channel, "text": message.text}
        extra = message.extra_data or {}
        if extra.get("thread_ts"):
            payload["thread_ts"] = extra["thread_ts"]

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    _API,
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                )
            data = resp.json()
        except Exception:
            logger.exception("Slack chat.postMessage transport error for %s", channel)
            raise

        if not data.get("ok"):
            # Surface as an exception so delivery.py retries instead of dropping.
            raise RuntimeError(
                f"slack chat.postMessage failed: {data.get('error')} (channel={channel})"
            )
        return data.get("ts")

    async def start(self) -> None:
        self._ensure_app()

    async def stop(self) -> None:
        self._app = None
