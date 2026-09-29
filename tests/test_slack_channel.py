"""Slack channel outbound + webhook routing tests."""

import pytest

from aios.channels.base import OutboundMessage
from aios.channels.slack import SlackChannel


class _FakeClient:
    def __init__(self, channel):
        self.channel = channel
        self.calls = []

    async def chat_postMessage(self, channel, text):
        self.calls.append((channel, text))
        return {"ts": "123.456"}


class _FakeApp:
    def __init__(self, channel):
        self.client = _FakeClient(channel)


class _FakeConn:
    def __init__(self, config):
        self.config = config
        self.channel_type = "slack"


class TestSlackOutbound:
    """Regression: agent replies must reach Slack.

    delivery.py builds a fresh channel per send, so anything relying on start()
    at boot never delivers. Lazy init is what makes outbound work.
    """

    async def test_send_works_without_start(self):
        conn = _FakeConn({"bot_token": "xoxb-test"})
        ch = SlackChannel(connection=conn)
        ch._app = _FakeApp("C1")

        msg = OutboundMessage(
            conversation_id="conv1",
            text="olá",
            channel_connection_id="c1",
            extra_data={"channel_id": "C1"},
        )
        ts = await ch.send(msg)
        assert ts == "123.456"
        assert ch._app.client.calls == [("C1", "olá")]

    async def test_resolves_channel_id_key(self):
        """Inbound stores 'channel_id'; send must read that, not 'channel'."""
        conn = _FakeConn({"bot_token": "xoxb-test"})
        ch = SlackChannel(connection=conn)
        app = _FakeApp("C9")
        ch._app = app

        msg = OutboundMessage(
            conversation_id="c",
            text="oi",
            channel_connection_id="c",
            extra_data={"channel_id": "C9"},
        )
        await ch.send(msg)
        assert app.client.calls[0][0] == "C9"

    async def test_legacy_channel_key_still_works(self):
        conn = _FakeConn({"bot_token": "xoxb-test"})
        ch = SlackChannel(connection=conn)
        app = _FakeApp("CLEGACY")
        ch._app = app

        msg = OutboundMessage(
            conversation_id="c", text="x", channel_connection_id="c",
            extra_data={"channel": "CLEGACY"},
        )
        await ch.send(msg)
        assert app.client.calls[0][0] == "CLEGACY"

    async def test_falls_back_to_default_channel(self):
        conn = _FakeConn({"bot_token": "xoxb-test", "default_channel": "CDEF"})
        ch = SlackChannel(connection=conn)
        app = _FakeApp("CDEF")
        ch._app = app

        msg = OutboundMessage(
            conversation_id="c", text="x", channel_connection_id="c", extra_data={},
        )
        await ch.send(msg)
        assert app.client.calls[0][0] == "CDEF"

    async def test_no_token_returns_none(self):
        ch = SlackChannel(connection=_FakeConn({}))
        msg = OutboundMessage(
            conversation_id="c", text="x", channel_connection_id="c",
            extra_data={"channel_id": "C1"},
        )
        assert await ch.send(msg) is None

    async def test_no_channel_returns_none(self):
        ch = SlackChannel(connection=_FakeConn({"bot_token": "t"}))
        msg = OutboundMessage(
            conversation_id="c", text="x", channel_connection_id="c", extra_data={},
        )
        assert await ch.send(msg) is None

    async def test_send_failure_propagates_for_retry(self):
        """A Slack API error must raise so delivery.py retries, not silently drop."""
        class _Boom:
            class client:
                @staticmethod
                async def chat_postMessage(channel, text):
                    raise RuntimeError("rate_limited")

        ch = SlackChannel(connection=_FakeConn({"bot_token": "t"}))
        ch._app = _Boom()
        msg = OutboundMessage(
            conversation_id="c", text="x", channel_connection_id="c",
            extra_data={"channel_id": "C1"},
        )
        with pytest.raises(RuntimeError):
            await ch.send(msg)


class TestSlackChannelRouting:
    """Each manager/orchestrator channel routes to its own connection."""

    def test_matches_slack_channel_id(self):
        class _C:
            def __init__(self, cfg):
                self.config = cfg

        conns = [
            _C({"slack_channel_id": "CMGR1"}),
            _C({"slack_channel_id": "CORCH1"}),
            _C({}),
        ]
        assert conns[0] is self._pick(conns, "CMGR1")
        assert conns[1] is self._pick(conns, "CORCH1")

    def test_unmatched_falls_back_to_first(self):
        class _C:
            def __init__(self, cfg):
                self.config = cfg

        conns = [_C({"slack_channel_id": "A"}), _C({})]
        assert conns[0] is self._pick(conns, "CUNKNOWN")

    @staticmethod
    def _pick(conns, channel_id):
        """Mirror of _find_connection's selection logic."""
        for c in conns:
            cfg = c.config or {}
            if isinstance(cfg, dict) and cfg.get("slack_channel_id") == channel_id:
                return c
        return conns[0] if conns else None
