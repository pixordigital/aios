"""Security API: incident creation and governed response."""

import pytest


async def test_create_incident(auth_client):
    resp = await auth_client.post("/api/security/incidents", json={"title": "Probe detection", "severity": "high"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "detected"


async def test_response_authority_deterministic(auth_client):
    created = (
        await auth_client.post("/api/security/incidents", json={"title": "Probe 2", "severity": "low"})
    )
    assert created.status_code == 200, created.text
    incident_id = created.json()["id"]

    resp = await auth_client.post(
        f"/api/security/incidents/{incident_id}/respond", json={"action": "delete_data", "actor_type": "human"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["allowed"] is False
    assert body["level"] == "human"

    resp = await auth_client.post(
        f"/api/security/incidents/{incident_id}/respond", json={"action": "preserve_logs", "actor_type": "agent"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["allowed"] is True


async def test_close_incident(auth_client):
    created = await auth_client.post("/api/security/incidents", json={"title": "Probe 3", "severity": "info"})
    assert created.status_code == 200, created.text
    incident_id = created.json()["id"]
    resp = await auth_client.post(
        f"/api/security/incidents/{incident_id}/close", json={"status": "closed"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "closed"


async def test_missing_incident_is_404(auth_client):
    resp = await auth_client.post("/api/security/incidents/missing/respond", json={"action": "preserve_logs"})
    assert resp.status_code == 404, resp.text
