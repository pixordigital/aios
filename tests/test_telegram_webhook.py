"""Phase 6 gate: Telegram webhook auth/dedupe + poll-lease loss."""

import asyncio
from types import SimpleNamespace

import pytest

from aios.channels import telegram as telegram_mod
from aios.channels.telegram import TelegramChannel
from aios.db.models import ChannelConnection, Organization


@pytest.fixture
async def telegram_conn(test_db_session):
    org = Organization(name="Telegram Org", slug="tg-org", extra_data={"plan": "pro"})
    test_db_session.add(org)
    await test_db_session.commit()
    await test_db_session.refresh(org)
    conn = ChannelConnection(
        org_id=org.id,
        channel_type="telegram",
        config={"bot_token": "123:abc"},
        is_active=True,
    )
    test_db_session.add(conn)
    await test_db_session.commit()
    await test_db_session.refresh(conn)
    return conn


@pytest.mark.asyncio(loop_scope="function")
async def test_webhook_fails_closed_without_secret(async_client, telegram_conn, monkeypatch):
    monkeypatch.setattr(telegram_mod.settings, "telegram_webhook_secret", "")
    resp = await async_client.post(
        f"/api/telegram/webhook/{telegram_conn.id}", json={"message": {}}
    )
    assert resp.status_code == 503


@pytest.mark.asyncio(loop_scope="function")
async def test_webhook_rejects_wrong_secret(async_client, telegram_conn, monkeypatch):
    monkeypatch.setattr(telegram_mod.settings, "telegram_webhook_secret", "right")
    resp = await async_client.post(
        f"/api/telegram/webhook/{telegram_conn.id}",
        json={"message": {}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio(loop_scope="function")
async def test_webhook_dispatches_with_stable_msg_id(
    async_client, telegram_conn, monkeypatch
):
    monkeypatch.setattr(telegram_mod.settings, "telegram_webhook_secret", "s3cret")
    seen = []

    async def fake_dispatch(**kw):
        seen.append(kw)

    async def fake_ack(*a, **kw):
        return None

    monkeypatch.setattr("aios.core.dispatch.dispatch_inbound", fake_dispatch)
    monkeypatch.setattr("aios.core.owner_notify.ack_notification", fake_ack)

    payload = {
        "update_id": 1,
        "message": {
            "message_id": 42,
            "chat": {"id": 555, "type": "private"},
            "from": {"id": 7, "username": "alice"},
            "text": "hello",
        },
    }
    for _ in range(2):  # Telegram redelivery
        resp = await async_client.post(
            f"/api/telegram/webhook/{telegram_conn.id}",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"},
        )
        assert resp.status_code == 200

    assert len(seen) == 2
    assert seen[0]["extra_data"]["msg_id"] == "telegram:555:42"
    assert seen[0]["channel_connection_id"] == telegram_conn.id


@pytest.mark.asyncio(loop_scope="function")
async def test_poll_loop_stops_when_lease_is_lost(monkeypatch):
    calls = {"renew": 0}

    class FakePool:
        def __init__(self):
            self.data = {}

        async def set(self, key, value, nx=False, ex=None, xx=False):
            if nx and key in self.data:
                return None
            if xx and key not in self.data:
                return None
            self.data[key] = value
            return True

        async def eval(self, script, numkeys, key, owner, ttl=None):
            calls["renew"] += 1
            return 0  # someone else owns the lease now

    class FakeResp:
        def json(self):
            return {"ok": True, "result": []}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return FakeResp()

    async def fake_pool():
        return FakePool()

    monkeypatch.setattr("aios.tasks.queue.get_redis_pool", fake_pool)
    monkeypatch.setattr(telegram_mod.httpx, "AsyncClient", lambda *a, **k: FakeClient())

    channel = TelegramChannel(
        connection=SimpleNamespace(id="c1", config={"bot_token": "t"}, org_id="o1")
    )
    channel._running = True
    await asyncio.wait_for(channel._poll_loop("t"), timeout=5)

    assert channel._running is False, "lease loss must stop the loop"
    assert calls["renew"] == 1
