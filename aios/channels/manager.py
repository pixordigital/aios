"""Channel lifecycle manager — start/stop channel adapters."""

from typing import Any
import logging
from aios.channels.base import Channel
from aios.channels.web import WebChannel
from aios.channels.slack import SlackChannel
from aios.channels.telegram import TelegramChannel
from aios.channels.email_ import EmailChannel
from aios.channels.evolution import EvolutionChannel
from aios.channels.voice import VoiceChannel

logger = logging.getLogger(__name__)

CHANNEL_REGISTRY: dict[str, Any] = {
    "web": WebChannel,
    "slack": SlackChannel,
    "telegram": TelegramChannel,
    "email": EmailChannel,
    "evolution": EvolutionChannel,
    "voice": VoiceChannel,
}


class ChannelManager:
    """Manages active channel instances."""

    def __init__(self):
        self._instances: dict[str, Channel] = {}

    def build(self, connection, agent_or_team=None, db=None) -> Channel:
        cls = CHANNEL_REGISTRY.get(connection.channel_type)
        if not cls:
            raise ValueError(f"Unknown channel type: {connection.channel_type}")
        # Fail loud. Swallowing this left the channel holding "enc:<fernet>"
        # as its api_key, so every send went out with a ciphertext credential
        # and came back 401 — indistinguishable from bad credentials.
        from aios.core.secrets import decrypt_channel_config
        if connection.config and any(str(v).startswith("enc:") for v in connection.config.values() if isinstance(v, str)):
            connection.config = decrypt_channel_config(connection.config)
        return cls(connection=connection, agent_or_team=agent_or_team, db=db)

    def register(self, connection_id: str, channel: Channel) -> None:
        """Track a live adapter so it can be started/stopped on demand.

        `main.py` started every active channel once at boot and nothing else did:
        a channel created or re-enabled afterwards never opened its poll loop
        (Telegram/Email receive nothing), and one disabled kept polling and
        replying. Both paths call sync_channel(connection, is_active).
        """
        if connection_id:
            self._instances[connection_id] = channel

    def unregister(self, connection_id: str) -> None:
        self._instances.pop(connection_id, None)

    async def start(self, channel: Channel) -> None:
        await channel.start()
        cid = getattr(getattr(channel, "connection", None), "id", "")
        self.register(cid or "", channel)
        logger.info("Channel %s started", channel.channel_type)

    async def stop(self, channel: Channel) -> None:
        await channel.stop()
        cid = getattr(getattr(channel, "connection", None), "id", "")
        self.unregister(cid or "")
        logger.info("Channel %s stopped", channel.channel_type)

    async def sync(self, connection, is_active: bool, agent_or_team=None, db=None) -> bool:
        """Start or stop one connection's adapter. Returns True when running.

        Self-contained on purpose: the caller is an API route and has no access
        to the objects `main.py` built during lifespan.
        """
        cid = getattr(connection, "id", "")
        existing = self._instances.get(cid)
        if not is_active:
            if existing is not None:
                try:
                    await self.stop(existing)
                except Exception:
                    logger.exception("stop channel %s failed", cid)
            elif cid:
                self.unregister(cid)
            return False
        if existing is not None:
            return True
        channel = self.build(connection, agent_or_team, db)
        await self.start(channel)
        return True


manager = ChannelManager()
