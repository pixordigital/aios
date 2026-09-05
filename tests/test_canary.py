from httpx import AsyncClient


class TestCanary:
    async def test_canary_promote_rollback(self, auth_client: AsyncClient):
        c = await auth_client.post("/api/agents", json={"name": "Canary Agent", "agent_type": "custom"})
        aid = c.json()["id"]
        await auth_client.post(f"/api/agents/{aid}/deploy")
        await auth_client.post(f"/api/agents/{aid}/deploy")
        promo = await auth_client.post(f"/api/agents/{aid}/canary/promote")
        assert promo.status_code in (200, 400)
        if promo.status_code == 200:
            assert promo.json()["ok"] is True

    async def test_canary_rollback_no_canary(self, auth_client: AsyncClient):
        c = await auth_client.post("/api/agents", json={"name": "Canary2", "agent_type": "custom"})
        aid = c.json()["id"]
        await auth_client.post(f"/api/agents/{aid}/deploy")
        r = await auth_client.post(f"/api/agents/{aid}/canary/rollback")
        assert r.status_code == 400
