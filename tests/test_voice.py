"""Voice channel tests — providers, call validation, webhook auth, tool registry."""

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

    async def test_tool_registered(self):
        from aios.tools.registry import TOOL_REGISTRY
        import aios.tools  # noqa: F401 — triggers registration
        assert "voice_call" in TOOL_REGISTRY

    async def test_voice_tool_validation(self):
        from aios.tools.voice_call import VoiceCallTool
        t = VoiceCallTool()
        r = await t.run(to="", script="")
        assert "error" in r


class TestVoiceTenantScope:
    async def test_cross_tenant_voice_channel_access_records_metric(self, auth_client, test_db_session, second_org):
        from sqlalchemy import select

        from aios.db.models import ChannelConnection
        from aios.governance.security import SecurityEvent

        other = ChannelConnection(
            org_id=second_org.id,
            channel_type="voice",
            label="Other Org Voice",
            config={"provider": "selfhosted"},
        )
        test_db_session.add(other)
        await test_db_session.commit()
        await test_db_session.refresh(other)

        cases = [
            ("post", "/api/voice/say", {"text": "ola", "channel_id": other.id}, "voice.api.say"),
            ("post", "/api/voice/call", {"to": "+5511999999999", "script": "oi", "channel_id": other.id}, "voice.api.call"),
        ]
        for method, path, body, source in cases:
            resp = await getattr(auth_client, method)(path, json=body)
            assert resp.status_code == 404, (path, resp.text)

        rows = (
            await test_db_session.execute(
                select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
            )
        ).scalars().all()
        for _, _, _, source in cases:
            assert any(
                e.payload.get("metric") == "cross_tenant_block"
                and e.payload.get("resource_type") == "ChannelConnection"
                and e.payload.get("resource_org_id") == second_org.id
                and e.payload.get("channel_id") == other.id
                and e.source == source
                for e in rows
            ), source
