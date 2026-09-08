"""Health + RAG readiness — próximo passo 100%."""
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_health_includes_rag(async_client: AsyncClient):
    r = await async_client.get("/health")
    assert r.status_code == 200
    j = r.json()
    assert "rag" in j
    assert "vector" in j["rag"]
    assert "db" in j

@pytest.mark.asyncio
async def test_health_ready_checks(async_client: AsyncClient):
    r = await async_client.get("/health/ready")
    # 200 ready or 503 not_ready depending on test DB
    assert r.status_code in (200, 503)
    j = r.json()
    assert "checks" in j
    assert "db" in j["checks"]

@pytest.mark.asyncio
async def test_health_live(async_client: AsyncClient):
    r = await async_client.get("/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "live"
