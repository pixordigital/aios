"""Voice channel tests — providers, call validation, webhook auth, tool registry."""

import pytest
from httpx import AsyncClient


class TestVoice:
    async def test_providers_requires_auth(self, async_client: AsyncClient):
        r = await async_client.get("/api/voice/providers")
        assert r.status_code == 401

    async def test_providers(self, auth_client: AsyncClient):
        r = await auth_client.get("/api/voice/providers")
        assert r.status_code == 200
        j = r.json()
        assert "elevenlabs" in j["providers"]
        assert "selfhosted" in j["providers"]
        assert "vapi" in j["providers"]
        assert "retell" in j["providers"]

    async def test_say_validation(self, auth_client: AsyncClient):
        r = await auth_client.post("/api/voice/say", json={"text": ""})
        assert r.status_code == 422

    async def test_say_no_provider(self, auth_client: AsyncClient):
        r = await auth_client.post("/api/voice/say", json={"text": "Olá, teste"})
        assert r.status_code in (200, 502)

    async def test_call_rejects_bad_agent(self, auth_client: AsyncClient):
        r = await auth_client.post("/api/voice/call", json={"to": "+5511999999999", "script": "Oi", "agent_id": "nope"})
        assert r.status_code == 400

    async def test_call_queued_without_bridge(self, auth_client: AsyncClient):
        r = await auth_client.post("/api/voice/call", json={"to": "+5511999999999", "script": "Olá, aqui é o SDR. Pode falar?"})
        assert r.status_code == 200
        j = r.json()
        assert j["ok"] is True
        assert j["status"] in ("queued", "dialing", "bridge_error")
        assert "conversation_id" in j

    async def test_call_rejects_custom_agent(self, auth_client: AsyncClient, test_session, test_org):
        from aios.db.models import Agent
        ag = Agent(org_id=test_org.id, name="Custom", agent_type="custom")
        test_session.add(ag)
        await test_session.commit()
        r = await auth_client.post("/api/voice/call", json={"to": "+5511999999999", "script": "Oi", "agent_id": ag.id})
        assert r.status_code == 400

    async def test_webhook_rejects_no_secret(self, async_client: AsyncClient):
        r = await async_client.post("/api/voice/webhook", json={"from": "+5511999999999", "text": "oi"})
        assert r.status_code == 401

    async def test_webhook_rejects_empty(self, async_client: AsyncClient):
        from aios.config import settings
        settings.voice_webhook_secret = "test-voice-secret"
        r = await async_client.post("/api/voice/webhook?secret=test-voice-secret", json={"from": "+5511999999999"})
        assert r.status_code == 400

    async def test_channel_test_voice(self, auth_client: AsyncClient):
        r = await auth_client.post("/api/channels/test", json={"channel_type": "voice", "config": {"provider": "selfhosted"}})
        assert r.status_code == 200
        assert "ok" in r.json()

    async def test_vapi_no_creds_falls_back(self):
        from aios.core.voice import place_call
        r = await place_call("+5511999999999", "Oi", {"provider": "vapi"})
        assert r["ok"] is True
        assert r["status"] in ("queued", "bridge_error")

    async def test_retell_no_creds_falls_back(self):
        from aios.core.voice import place_call
        r = await place_call("+5511999999999", "Oi", {"provider": "retell"})
        assert r["ok"] is True
        assert r["status"] in ("queued", "bridge_error")

    async def test_room_requires_auth(self, async_client: AsyncClient):
        r = await async_client.post("/api/voice/room", json={})
        assert r.status_code == 401

    async def test_room_409_without_livekit(self, auth_client: AsyncClient):
        r = await auth_client.post("/api/voice/room", json={})
        assert r.status_code == 409

    async def test_room_rejects_bad_agent(self, auth_client: AsyncClient):
        from aios.config import settings
        settings.livekit_url = "ws://livekit:7880"
        settings.livekit_api_key = "devkey"
        settings.livekit_api_secret = "test-secret"
        try:
            r = await auth_client.post("/api/voice/room", json={"agent_id": "nope"})
            assert r.status_code == 400
        finally:
            settings.livekit_url = ""
            settings.livekit_api_key = ""
            settings.livekit_api_secret = ""

    async def test_tool_registered(self):
        from aios.tools.registry import TOOL_REGISTRY
        import aios.tools  # noqa: F401 — triggers registration
        assert "voice_call" in TOOL_REGISTRY

    async def test_voice_tool_validation(self):
        from aios.tools.voice_call import VoiceCallTool
        t = VoiceCallTool()
        r = await t.run(to="", script="")
        assert "error" in r
