"""Slack channel outbound + webhook routing tests.

Outbound goes through httpx to the Web API. httpx.AsyncClient is patched so no
network call is made in tests.
"""

import pytest

from aios.channels.base import OutboundMessage
from aios.channels.slack import SlackChannel


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    """Stands in for httpx.AsyncClient in a `async with` block."""

    def __init__(self, recorder, ok=True, error=None):
        self._recorder = recorder
        self._ok = ok
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        self._recorder.append({"url": url, "json": json, "headers": headers})
        if self._ok:
            return _FakeResponse({"ok": True, "ts": "123.456"})
        return _FakeResponse({"ok": False, "error": self._error})


def _patch(monkeypatch, ok=True, error=None, raise_exc=False):
    calls = []

    def _factory(*a, **kw):
        if raise_exc:
            raise RuntimeError("connection reset")
        return _FakeClient(calls, ok=ok, error=error)

    monkeypatch.setattr("aios.channels.slack.httpx.AsyncClient", _factory)
    return calls


class _Conn:
    def __init__(self, config):
        self.config = config
        self.channel_type = "slack"


def _msg(extra):
    return OutboundMessage(
        conversation_id="c", text="olá", channel_connection_id="c", extra_data=extra
    )


class TestSlackOutbound:
    """Regression: agent replies must reach Slack.

    delivery.py builds a fresh channel per send, so anything relying on start()
    at boot never delivers.
    """

    async def test_send_works_without_start(self, monkeypatch):
        calls = _patch(monkeypatch)
        ch = SlackChannel(connection=_Conn({"bot_token": "xoxb-test"}))
        assert ch._app is None
        ts = await ch.send(_msg({"channel_id": "C1"}))
        assert ts == "123.456"
        assert calls[0]["json"]["channel"] == "C1"
        assert calls[0]["headers"]["Authorization"] == "Bearer xoxb-test"

    async def test_resolves_channel_id_key(self, monkeypatch):
        """Inbound stores 'channel_id'; send must read that, not 'channel'."""
        calls = _patch(monkeypatch)
        ch = SlackChannel(connection=_Conn({"bot_token": "t"}))
        await ch.send(_msg({"channel_id": "C9"}))
        assert calls[0]["json"]["channel"] == "C9"

    async def test_legacy_channel_key_still_works(self, monkeypatch):
        calls = _patch(monkeypatch)
        ch = SlackChannel(connection=_Conn({"bot_token": "t"}))
        await ch.send(_msg({"channel": "CLEGACY"}))
        assert calls[0]["json"]["channel"] == "CLEGACY"

    async def test_falls_back_to_config_channel(self, monkeypatch):
        calls = _patch(monkeypatch)
        ch = SlackChannel(
            connection=_Conn({"bot_token": "t", "slack_channel_id": "CDEF"})
        )
        await ch.send(_msg({}))
        assert calls[0]["json"]["channel"] == "CDEF"

    async def test_thread_ts_forwarded(self, monkeypatch):
        calls = _patch(monkeypatch)
        ch = SlackChannel(connection=_Conn({"bot_token": "t"}))
        await ch.send(_msg({"channel_id": "C1", "thread_ts": "111.222"}))
        assert calls[0]["json"]["thread_ts"] == "111.222"

    async def test_no_token_returns_none(self, monkeypatch):
        _patch(monkeypatch)
        ch = SlackChannel(connection=_Conn({}))
        assert await ch.send(_msg({"channel_id": "C1"})) is None

    async def test_no_channel_returns_none(self, monkeypatch):
        _patch(monkeypatch)
        ch = SlackChannel(connection=_Conn({"bot_token": "t"}))
        assert await ch.send(_msg({})) is None

    async def test_api_error_raises_for_retry(self, monkeypatch):
        """A Slack API error must raise so delivery.py retries, not silently drop."""
        _patch(monkeypatch, ok=False, error="rate_limited")
        ch = SlackChannel(connection=_Conn({"bot_token": "t"}))
        with pytest.raises(RuntimeError, match="rate_limited"):
            await ch.send(_msg({"channel_id": "C1"}))

    async def test_transport_error_propagates(self, monkeypatch):
        _patch(monkeypatch, raise_exc=True)
        ch = SlackChannel(connection=_Conn({"bot_token": "t"}))
        with pytest.raises(RuntimeError):
            await ch.send(_msg({"channel_id": "C1"}))


class TestSlackChannelRouting:
    """Each manager/orchestrator channel routes to its own connection."""

    @staticmethod
    def _pick(conns, channel_id):
        """Mirror of _find_connection's selection logic."""
        for c in conns:
            cfg = c.config or {}
            if isinstance(cfg, dict) and cfg.get("slack_channel_id") == channel_id:
                return c
        return conns[0] if conns else None

    def test_matches_slack_channel_id(self):
        class _C:
            def __init__(self, cfg):
                self.config = cfg

        conns = [_C({"slack_channel_id": "CMGR1"}), _C({"slack_channel_id": "CORCH1"})]
        assert conns[0] is self._pick(conns, "CMGR1")
        assert conns[1] is self._pick(conns, "CORCH1")

    def test_unmatched_falls_back_to_first(self):
        class _C:
            def __init__(self, cfg):
                self.config = cfg

        conns = [_C({"slack_channel_id": "A"}), _C({})]
        assert conns[0] is self._pick(conns, "CUNKNOWN")
