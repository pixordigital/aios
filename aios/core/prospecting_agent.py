"""Prospective prospecting agent: daily watchword send + channel posting."""

import logging

from aios.core.agent import AgentRuntime

logger = logging.getLogger(__name__)


class ProspectingAgent(AgentRuntime):
    """Sends the daily watchwords to the prospect channels.

    - __init__(agent, db_session_factory=None): as AgentRuntime; `_runtime`
      defaults to self so tests can substitute a fake runtime.
    - compile_messages(profile): profile doc + brief -> message list.
    - send_daily_watchwords(profile): sends via _runtime.send.
    - handle_posting(channel_type, message_id, message_metadata): POST to
      /api/{channel_type}; returns {"posted": True, "message_id": ...}.
    """

    def __init__(self, agent, db_session_factory=None):
        super().__init__(agent, db_session_factory)
        self._runtime = self

    def profile_doc(self):
        from aios.core import business_sdr

        return business_sdr.profile_doc_from_extra_data(self.agent.extra_data or {})

    def compile_messages(self, profile=None) -> list[dict]:
        """Profile doc + watchwords brief -> message list to send."""
        from aios.core import sdr_prompt

        p = profile or self.profile_doc()
        return [
            {"role": "system", "content": sdr_prompt.SDR_VOICE_PROMPT},
            {"role": "user", "content": sdr_prompt.modern_prospecting_brief(p)},
        ]

    async def send_daily_watchwords(self, profile=None) -> None:
        for msg in self.compile_messages(profile):
            await self._runtime.send(msg["content"])

    async def handle_posting(self, channel_type, message_id, message_metadata=None):
        """POST the posted message to /api/{channel_type} via the runtime.

        Sends via _runtime.send with the matching channel and returns
        {"posted": True, "message_id": <id from the send/API result>}.
        """
        sent = await self._runtime.send(
            message_id,
            channel=channel_type,
            metadata=message_metadata or {},
        )
        return {"posted": True, "message_id": sent or message_id}
