"""Telegram channel — long-poll getUpdates inbound, Bot API sendMessage outbound.

Uses the plain Bot HTTP API via httpx (already a dependency) instead of
python-telegram-bot, which was never installed: `import telegram` raised, so
`start()` could never open a poll loop and the channel received nothing while
the dashboard and the Pro plan both listed it as available.

Long-poll (getUpdates) rather than a webhook so no public TLS endpoint is
required for the tenant — consistent with how every other channel here works.
"""

import asyncio
import logging
import uuid

import httpx

from aios.channels.base import Channel, OutboundMessage

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org"
_POLL_TIMEOUT_S = 25  # Telegram caps long-poll at 30s; 25 leaves room for RTT
_MAX_MESSAGE_CHARS = 4096


class TelegramChannel(Channel):
    channel_type = "telegram"

    def __init__(self, connection=None, agent_or_team=None, db=None):
        self.connection = connection
        self.agent_or_team = agent_or_team
        self.db = db
        self._config = connection.config if connection else {}
        self._app = None
        self._running = False
        self._poll_task: asyncio.Task | None = None
        # Only process each update once. getUpdates returns the last 24h of
        # unacknowledged updates, so a restart replays them.
        self._seen: set[int] = set()

    def _ensure_token(self) -> str:
        """The bot token, or "" when unconfigured.

        delivery.py calls build() per send and gets a fresh instance, so start()
        at boot never reaches the object that actually delivers.
        """
        if self._app is not None:
            return self._app
        token = self._config.get("bot_token") or self._config.get("token") or ""
        if not token:
            logger.warning("Telegram send skipped: bot_token not configured")
            return ""
        self._app = token
        return self._app

    def _resolve_chat(self, message: OutboundMessage) -> str:
        extra = message.extra_data or {}
        return str(
            extra.get("chat_id")
            or self._config.get("chat_id")
            or self._config.get("telegram_chat_id")
            or ""
        )

    async def send(self, message: OutboundMessage) -> str | None:
        chat_id = self._resolve_chat(message)
        if not chat_id:
            logger.warning("Telegram send skipped: no chat_id in extra_data or config")
            return None
        token = self._ensure_token()
        if not token:
            return None

        extra = message.extra_data or {}
        payload: dict = {"chat_id": chat_id, "text": message.text[:_MAX_MESSAGE_CHARS]}
        # reply_to_message_id threads the answer under the customer's question.
        if extra.get("reply_to_message_id"):
            payload["reply_to_message_id"] = extra["reply_to_message_id"]
        if extra.get("message_thread_id"):
            payload["message_thread_id"] = extra["message_thread_id"]

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{_API}/bot{token}/sendMessage", json=payload
                )
            data = resp.json()
        except Exception:
            logger.exception("Telegram transport error for chat %s", chat_id)
            raise

        if not data.get("ok"):
            # Raise so delivery.py's retry/DLQ applies instead of dropping.
            raise RuntimeError(f"telegram sendMessage failed: {data.get('description')}")
        return str(data.get("result", {}).get("message_id", ""))

    async def test(self) -> dict:
        token = self._config.get("bot_token") or self._config.get("token") or ""
        if not token:
            return {"ok": False, "message": "Missing bot token"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{_API}/bot{token}/getMe")
            data = resp.json()
            if not data.get("ok"):
                return {"ok": False, "message": data.get("description", "invalid token")}
            me = data.get("result", {})
            return {
                "ok": True,
                "message": f"Connected as @{me.get('username', 'bot')}",
                "details": {"id": me.get("id"), "username": me.get("username")},
            }
        except Exception as e:
            return {"ok": False, "message": str(e)}

    # ─── inbound long-poll ───

    async def start(self) -> None:
        token = self._ensure_token()
        if not token:
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop(token))
        logger.info("Telegram poll loop started")

    async def stop(self) -> None:
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):
                pass
            self._poll_task = None

    async def _poll_loop(self, token: str) -> None:
        """Poll getUpdates and dispatch inbound messages to the agent.

        Retries on any transport error with a fixed 5s pause: a blip must not
        kill the only inbound path for the channel.
        """
        offset = 0
        from aios.core.dispatch import dispatch_inbound

        # One poller per bot token. gunicorn runs --workers 2, so the lifespan
        # started two of these for the same connection, both long-polling the
        # same bot and both receiving the same pending updates.
        lock_key = f"aios:telegram-poll:{token[-8:]}"
        lock_held = ""

        while self._running:
            if not lock_held:
                try:
                    from aios.tasks.queue import get_redis_pool

                    pool = await get_redis_pool()
                    lock_held = f"{lock_key}:{uuid.uuid4().hex[:8]}"
                    # 60s > the 25s long-poll, so a healthy holder never expires
                    # between cycles and a dead process loses the token in a minute.
                    if not await pool.set(lock_held, 1, nx=True, ex=60):
                        lock_held = ""
                        await asyncio.sleep(30)
                        continue
                except Exception:
                    logger.warning(
                        "Telegram poll lock unavailable; polling without it", exc_info=True
                    )
            try:
                async with httpx.AsyncClient(timeout=_POLL_TIMEOUT_S + 10) as client:
                    resp = await client.get(
                        f"{_API}/bot{token}/getUpdates",
                        params={
                            "timeout": _POLL_TIMEOUT_S,
                            "offset": offset,
                            "allowed_updates": '["message"]',
                        },
                    )
                data = resp.json()
                if not data.get("ok"):
                    raise RuntimeError(data.get("description", "getUpdates failed"))

                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    if update["update_id"] in self._seen:
                        continue
                    self._seen.add(update["update_id"])
                    if len(self._seen) > 1000:
                        self._seen = set(list(self._seen)[-500:])

                    msg = update.get("message") or {}
                    chat = msg.get("chat") or {}
                    text = msg.get("text") or ""
                    if not text or not chat.get("id"):
                        continue

                    await dispatch_inbound(
                        channel_type="telegram",
                        channel_connection_id=getattr(self.connection, "id", "") or "",
                        conversation_id="",
                        text=text,
                        user_id=str(msg.get("from", {}).get("id", "")),
                        extra_data={
                            "chat_id": chat["id"],
                            "message_id": msg.get("message_id"),
                            "chat_type": chat.get("type"),
                            "username": msg.get("from", {}).get("username"),
                        },
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("Telegram poll error", exc_info=True)
                await asyncio.sleep(5)
            if lock_held:
                try:
                    from aios.tasks.queue import get_redis_pool

                    await (await get_redis_pool()).delete(lock_held)
                except Exception:
                    pass
                lock_held = ""