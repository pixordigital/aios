import pytest

from aios.config import settings


def test_settings_loaded():
    # Verify that critical settings have expected default values
    assert settings.app_name == "AIOS"
    assert settings.debug is True
    assert settings.https_only is True
    assert settings.rate_limit_per_minute == 60
    assert settings.jwt_algorithm == "HS256"

@pytest.mark.asyncio
async def test_health_endpoints(async_client):
    # Liveness
    resp_live = await async_client.get("/health/live")
    assert resp_live.status_code == 200
    assert resp_live.json().get("status") == "live"
    # Readiness
    resp_ready = await async_client.get("/health/ready")
    assert resp_ready.status_code == 200
    assert resp_ready.json().get("status") == "ready"
    # Overall health (should combine both)
    resp = await async_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("live") is True
    assert data.get("ready") is True
