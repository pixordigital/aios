import pytest
from aios.config import settings
from fastapi.testclient import TestClient
from aios.main import app

client = TestClient(app)

def test_settings_loaded():
    # Verify that critical settings have expected default values
    assert settings.app_name == "AIOS"
    assert settings.debug is True
    assert settings.https_only is True
    assert settings.rate_limit_per_minute == 60
    assert settings.jwt_algorithm == "HS256"

def test_health_endpoints():
    # Liveness
    resp_live = client.get("/health/live")
    assert resp_live.status_code == 200
    assert resp_live.json().get("status") == "live"
    # Readiness
    resp_ready = client.get("/health/ready")
    assert resp_ready.status_code == 200
    assert resp_ready.json().get("status") == "ready"
    # Overall health (should combine both)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("live") is True
    assert data.get("ready") is True
