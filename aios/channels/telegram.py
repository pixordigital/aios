"""Telegram channel — polling with python-telegram-bot."""

from aios.channels.base import Channel, OutboundMessage


class TelegramChannel(Channel):
    channel_type = "telegram"

    def __init__(self, connection=None, agent_or_team=None, db=None):
        self.connection = connection
        self.agent_or_team = agent_or_team
        self.db = db
        self._config = connection.config if connection else {}
        self._app = None
        self._running = False

    async def send(self, message: OutboundMessage) -> str | None:
        import telegram
        token = self._config.get("bot_token", "")
        chat_id = message.extra_data.get("chat_id") if message.extra_data else None
        if not token or not chat_id:
            return None
        bot = telegram.Bot(token=token)
        msg = await bot.send_message(chat_id=chat_id, text=message.text)
        return str(msg.message_id)

    async def start(self) -> None:
        pass  # ponytail: requires asyncio task mgmt; add when Telegram channel is used

    async def stop(self) -> None:
        self._running = False
