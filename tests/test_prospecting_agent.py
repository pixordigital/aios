"""Prospective prospecting agent: handle_posting via _runtime.send."""

import asyncio

from aios.core.prospecting_agent import ProspectingAgent


class FakeRuntime:
    """Records sends; send() returns a fixed id as the tools/API result."""

    def __init__(self, send_id="msg-1"):
        self.sends = []
        self.send_id = send_id

    async def send(self, message, channel=None, metadata=None):
        self.sends.append({"message": message, "channel": channel, "metadata": metadata})
        return self.send_id


class SimpleProspectingAgent(ProspectingAgent):
    """Lightweight ProspectingAgent: skips AgentRuntime.__init__."""

    def __init__(self, runtime):
        self._runtime = runtime


def test_handle_posting_websites_type():
    runtime = FakeRuntime()
    agent = SimpleProspectingAgent(runtime)
    result = asyncio.run(agent.handle_posting("websites", "m1", {"k": "v"}))
    assert runtime.sends[0]["channel"] == "websites"
    assert result["posted"] is True
    assert result["message_id"] == "msg-1"
