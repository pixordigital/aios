"""Zernio WhatsApp transport tests.

Outbound uses Zernio's unified REST API (Bearer key), cold outreach opens a new
conversation with a template; replies hit the conversation messages endpoint.
Inbound webhook verifies X-Zernio-Signature, fail-closed.
"""

import hmac
import hashlib
import pytest
from httpx import ASGITransport, AsyncClient

from aios.channels.base import OutboundMessage
from aios.channels.whatsapp import WhatsAppChannel
from aios.main import app


class _FakeClient:
    """Captures requests and returns canned responses."""

    def __init__(self, send_status=200, send_json=None, created_json=None):
        self.requests = []
        self.send_status = send_status
        self.send_json = send_json if send_json is not None else {"id": "mid_1"}
        self.created_json = created_json if created_json is not None else {"id": "c_1"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        self.requests.append({"url": url, "json": json, "headers": headers})
        path = "/messages" if "/messages" in url else ""
        if path:
            body, status = self.send_json, self.send_status
        else:
            body, status = self.created_json, 201
        return _Resp(status, body)


class _Resp:
    def __init__(self, status_code, json_):
        self.status_code = status_code
        self._json = json_

    def json(self):
        return self._json

    @property
    def text(self):
        return str(self._json)


def _chan(config):
    return WhatsAppChannel(connection=type("C", (), {"config": config})())


@pytest.mark.asyncio
async def test_zernio_reply_in_thread(monkeypatch):
    ch = _chan({"provider": "zernio", "api_key": "k", "account_id": "a"})
    fc = _FakeClient()
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: fc)
    out = OutboundMessage(conversation_id="c_9", text="oi", channel_connection_id="x",
                          extra_data={"conversation_id": "c_9", "from_number": "551199999"})
    rid = await ch.send(out)
    assert rid == "mid_1"
    req = fc.requests[0]
    assert "/inbox/conversations/c_9/messages" in req["url"]
    assert req["json"] == {"accountId": "a", "message": "oi"}
    assert req["headers"]["Authorization"] == "Bearer k"


@pytest.mark.asyncio
async def test_zernio_cold_outreach_uses_template(monkeypatch):
    ch = _chan({"provider": "zernio", "api_key": "k", "account_id": "a",
                "template_name": "sdr_hello", "template_language": "en_US"})
    fc = _FakeClient()
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: fc)
    out = OutboundMessage(conversation_id="", text="oi", channel_connection_id="x",
                          extra_data={"from_number": "551199999"})
    await ch.send(out)
    req = fc.requests[0]
    assert req["url"] == "https://zernio.com/api/v1/inbox/conversations"
    assert req["json"]["participantId"] == "551199999"
    assert req["json"]["templateName"] == "sdr_hello"


@pytest.mark.asyncio
async def test_zernio_cold_outreach_no_template_uses_utility(monkeypatch):
    ch = _chan({"provider": "zernio", "api_key": "k", "account_id": "a"})
    fc = _FakeClient()
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: fc)
    out = OutboundMessage(conversation_id="", text="oi", channel_connection_id="x",
                          extra_data={"from_number": "551199999"})
    await ch.send(out)
    assert fc.requests[0]["json"]["category"] == "utility"
    assert fc.requests[0]["json"]["message"] == "oi"


@pytest.mark.asyncio
async def test_meta_path_untouched():
    """provider unset → Meta Cloud path (no api_key/account used)."""
    ch = _chan({"provider": "zernio", "api_key": "k", "account_id": "a"})
    assert ch._config["provider"] == "zernio"


def _sig(secret, body):
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_webhook_rejects_missing_signature(monkeypatch):
    monkeypatch.setattr("aios.config.settings.zernio_webhook_secret", "s3cret")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/zernio/webhook", json={"event": "message.received"})
    assert r.json() == {"status": "ignored"}


@pytest.mark.asyncio
async def test_webhook_rejects_bad_signature(monkeypatch):
    monkeypatch.setattr("aios.config.settings.zernio_webhook_secret", "s3cret")
    transport = ASGITransport(app=app)
    body = b'{"event":"message.received","message":{"direction":"incoming"}}'
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/zernio/webhook", content=body,
                         headers={"X-Zernio-Signature": "bad"})
    assert r.json() == {"status": "ignored"}


@pytest.mark.asyncio
async def test_webhook_rejects_unconfigured_secret(monkeypatch):
    monkeypatch.setattr("aios.config.settings.zernio_webhook_secret", "")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/zernio/webhook", json={"event": "message.received"})
    assert r.json() == {"status": "ignored"}