"""Discord channel — gateway bot with discord.py."""

from aios.channels.base import Channel, OutboundMessage


class DiscordChannel(Channel):
    channel_type = "discord"

    def __init__(self, connection=None, agent_or_team=None, db=None):
        self.connection = connection
        self.agent_or_team = agent_or_team
        self.db = db
        self._config = connection.config if connection else {}
        self._bot = None

    async def send(self, message: OutboundMessage) -> str | None:
        if not self._bot:
            return None
        channel_id = message.extra_data.get("channel_id") if message.extra_data else None
        if not channel_id:
            return None
        import discord
        channel = self._bot.get_channel(int(channel_id))
        if channel:
            msg = await channel.send(message.text)
            return str(msg.id)
        return None

    async def start(self) -> None:
        pass  # ponytail: requires asyncio task; add when needed

    async def stop(self) -> None:
        if self._bot:
            await self._bot.close()
            self._bot = None
