"""Telegram was advertised in the dashboard and the Pro plan but had no inbound
path at all: it imported `python-telegram-bot`, which was never a dependency, so
`import telegram` raised and `start()` could never open a poll loop. Outbound
had the same shape — it built a `Bot` object and called it without
`initialize()`.

The channel now uses the plain Bot HTTP API via httpx, which is already a
dependency: long-poll `getUpdates` inbound, `sendMessage` outbound.
"""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aios.channels.base import OutboundMessage
from aios.channels.telegram import TelegramChannel


class _Conn:
    def __init__(self, **cfg):
        self.id = "conn-1"
        self.config = cfg


def _http(payload, status=200):
    resp = MagicMock()
    resp.json = MagicMock(return_value=payload)
    resp.status_code = status
    resp.raise_for_status = MagicMock()
    post = AsyncMock(return_value=resp)
    get = AsyncMock(return_value=resp)
    client = MagicMock()
    client.post = post
    client.get = get
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, post, get


def _poll_client(payloads, on_call=None):
    """httpx client that returns each payload in turn, then keeps answering.

    The loop must be stopped from the mock: an AsyncMock never yields to the
    event loop, so a `wait_for` timeout could not fire and the test would spin.
    """
    seq = list(payloads)

    async def _get(*a, **k):
        payload = seq.pop(0) if len(seq) > 1 else seq[0]
        if on_call:
            on_call()
        resp = MagicMock()
        resp.json = MagicMock(return_value=payload)
        return resp

    client = MagicMock()
    client.get = _get
    client.post = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
async def test_telegram_send_uses_the_bot_api():
    ch = TelegramChannel(connection=_Conn(bot_token="123:ABC"))
    cm, post, _ = _http({"ok": True, "result": {"message_id": 55}})
    with patch("httpx.AsyncClient", return_value=cm):
        mid = await ch.send(
            OutboundMessage("c1", "hi", "conn-1", {"chat_id": 123, "reply_to_message_id": 9})
        )
    assert mid == "55"
    assert "bot123:ABC/sendMessage" in post.await_args[0][0]
    body = post.await_args[1]["json"]
    assert str(body["chat_id"]) == "123"  # normalised to str for the Bot API
    assert body["reply_to_message_id"] == 9


@pytest.mark.asyncio
async def test_telegram_send_raises_on_api_error():
    """A raise, not a silent None: delivery.py's retry/DLQ must apply."""
    ch = TelegramChannel(connection=_Conn(bot_token="123:ABC"))
    cm, _, _ = _http({"ok": False, "description": "chat not found"})
    with patch("httpx.AsyncClient", return_value=cm):
        with pytest.raises(RuntimeError):
            await ch.send(OutboundMessage("c1", "hi", "conn-1", {"chat_id": 1}))


@pytest.mark.asyncio
async def test_telegram_send_without_token_is_a_skip_not_a_crash():
    ch = TelegramChannel(connection=_Conn())
    assert await ch.send(OutboundMessage("c1", "hi", "conn-1", {"chat_id": 1})) is None


@pytest.mark.asyncio
async def test_telegram_no_longer_imports_a_missing_package():
    """`import telegram` raised because python-telegram-bot is not a dependency,
    so the old send() and start() could never run."""
    ch = TelegramChannel(connection=_Conn(bot_token="123:ABC"))
    cm, _, _ = _http({"ok": True, "result": {"message_id": 1}})
    with patch("httpx.AsyncClient", return_value=cm):
        assert await ch.send(OutboundMessage("c1", "hi", "conn-1", {"chat_id": 1})) == "1"


@pytest.mark.asyncio
async def test_telegram_poll_loop_dispatches_inbound():
    """start() was `pass`, so inbound never existed. This proves a message in
    getUpdates reaches dispatch_inbound."""
    ch = TelegramChannel(connection=_Conn(bot_token="123:ABC"))
    batch = {
        "ok": True,
        "result": [
            {
                "update_id": 10,
                "message": {
                    "message_id": 3,
                    "chat": {"id": 777, "type": "private"},
                    "from": {"id": 42, "username": "ana"},
                    "text": "quero orcamento",
                },
            }
        ],
    }
    dispatched = []

    async def _fake_dispatch(**kw):
        dispatched.append(kw)
        ch._running = False

    cm = _poll_client([batch], on_call=lambda: setattr(ch, "_running", False))
    pool = MagicMock()
    pool.set = AsyncMock(return_value=True)
    pool.delete = AsyncMock()
    with patch("httpx.AsyncClient", return_value=cm), patch(
        "aios.core.dispatch.dispatch_inbound", _fake_dispatch
    ), patch("aios.tasks.queue.get_redis_pool", AsyncMock(return_value=pool)):
        ch._running = True
        await asyncio.wait_for(ch._poll_loop("123:ABC"), timeout=5)

    assert dispatched, "getUpdates result never reached dispatch_inbound"
    assert dispatched[0]["text"] == "quero orcamento"
    assert dispatched[0]["extra_data"]["chat_id"] == 777
    assert dispatched[0]["user_id"] == "42"
    # the reply must be able to find its way back to the same chat
    assert dispatched[0]["channel_connection_id"] == "conn-1"


@pytest.mark.asyncio
async def test_telegram_poll_loop_skips_replayed_updates():
    """getUpdates returns the last 24h unacknowledged, so a restart replays
    them; without _seen the customer is answered twice."""
    ch = TelegramChannel(connection=_Conn(bot_token="123:ABC"))
    ch._seen = {10}
    batch = {
        "ok": True,
        "result": [
            {
                "update_id": 10,
                "message": {"message_id": 3, "chat": {"id": 1}, "from": {"id": 1}, "text": "x"},
            }
        ],
    }
    dispatched = []

    async def _dispatch(**kw):
        dispatched.append(kw)

    cm = _poll_client([batch], on_call=lambda: setattr(ch, "_running", False))
    pool = MagicMock()
    pool.set = AsyncMock(return_value=True)
    pool.delete = AsyncMock()
    with patch("httpx.AsyncClient", return_value=cm), patch(
        "aios.core.dispatch.dispatch_inbound", _dispatch
    ), patch("aios.tasks.queue.get_redis_pool", AsyncMock(return_value=pool)):
        ch._running = True
        await asyncio.wait_for(ch._poll_loop("123:ABC"), timeout=5)
    assert not dispatched, "a replayed update was dispatched again"


@pytest.mark.asyncio
async def test_telegram_poll_loop_survives_a_transport_error():
    """A blip must not kill the only inbound path for the channel."""
    ch = TelegramChannel(connection=_Conn(bot_token="123:ABC"))
    calls = {"n": 0}

    async def _boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("network down")
        ch._running = False
        resp = MagicMock()
        resp.json = MagicMock(return_value={"ok": True, "result": []})
        return resp

    client = MagicMock()
    client.get = _boom
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=cm), patch(
        "asyncio.sleep", AsyncMock()
    ):
        ch._running = True
        await asyncio.wait_for(ch._poll_loop("123:ABC"), timeout=5)

    assert calls["n"] >= 2, "the loop gave up after one transport error"


@pytest.mark.asyncio
async def test_telegram_start_without_token_opens_no_task():
    ch = TelegramChannel(connection=_Conn())
    await ch.start()
    assert ch._poll_task is None