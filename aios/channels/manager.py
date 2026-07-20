"""Channel lifecycle manager — start/stop channel adapters."""

import logging
from aios.channels.base import Channel
from aios.channels.web import WebChannel
from aios.channels.whatsapp import WhatsAppChannel
from aios.channels.slack import SlackChannel
from aios.channels.telegram import TelegramChannel
from aios.channels.discord import DiscordChannel
from aios.channels.email_ import EmailChannel

logger = logging.getLogger(__name__)

CHANNEL_REGISTRY = {
    "web": WebChannel,
    "whatsapp": WhatsAppChannel,
    "slack": SlackChannel,
    "telegram": TelegramChannel,
    "discord": DiscordChannel,
    "email": EmailChannel,
}


class ChannelManager:
    """Manages active channel instances."""

    def __init__(self):
        self._instances: dict[str, Channel] = {}

    def build(self, connection, agent_or_team=None, db=None) -> Channel:
        cls = CHANNEL_REGISTRY.get(connection.channel_type)
        if not cls:
            raise ValueError(f"Unknown channel type: {connection.channel_type}")
        return cls(connection=connection, agent_or_team=agent_or_team, db=db)

    async def start(self, channel: Channel) -> None:
        await channel.start()
        logger.info("Channel %s started", channel.channel_type)

    async def stop(self, channel: Channel) -> None:
        await channel.stop()
        logger.info("Channel %s stopped", channel.channel_type)


manager = ChannelManager()
