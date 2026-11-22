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

    # caller-supplied actor_type/preapproved must not grant authority
    resp = await auth_client.post(
        f"/api/security/incidents/{incident_id}/respond",
        json={"action": "delete_data", "actor_type": "agent", "preapproved": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["allowed"] is False
    assert body["level"] == "human"
    assert body["actor_type"] == "human"
    assert body["preapproval_source"] is None

    resp = await auth_client.post(
        f"/api/security/incidents/{incident_id}/respond", json={"action": "preserve_logs", "actor_type": "agent"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["allowed"] is True
    assert body["event_id"]


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


async def test_metrics_endpoint(auth_client):
    resp = await auth_client.get("/api/security/metrics")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "mttd_minutes" in body
    assert "mtta_minutes" in body
    assert "mttr_minutes" in body
    assert "false_positive_rate" in body
    assert "coverage" in body
    assert "unresolved_critical_vulns" in body
    assert body["metric_sources"]["unresolved_critical_vulns"].startswith("unknown:")


async def test_security_events_list_ingest(auth_client):
    created = await auth_client.post("/api/security/incidents", json={"title": "Evt", "severity": "low"})
    incident_id = created.json()["id"]
    ing = await auth_client.post(
        "/api/security/events",
        json={"event_type": "security.unauthorized_attempt", "severity": "high", "incident_id": incident_id, "payload": {"ip": "1.2.3.4"}},
    )
    assert ing.status_code == 200, ing.text
    assert ing.json()["stored"] is True
    listed = await auth_client.get(f"/api/security/events?incident_id={incident_id}")
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert any(i["event_type"] == "security.unauthorized_attempt" for i in items)


async def test_respond_closed_incident_conflict(auth_client):
    created = await auth_client.post("/api/security/incidents", json={"title": "Closed", "severity": "low"})
    incident_id = created.json()["id"]
    closed = await auth_client.post(f"/api/security/incidents/{incident_id}/close", json={"status": "closed"})
    assert closed.status_code == 200, closed.text
    resp = await auth_client.post(f"/api/security/incidents/{incident_id}/respond", json={"action": "preserve_logs"})
    assert resp.status_code == 409, resp.text


async def test_close_invalid_status(auth_client):
    created = await auth_client.post("/api/security/incidents", json={"title": "Bad status", "severity": "low"})
    incident_id = created.json()["id"]
    resp = await auth_client.post(f"/api/security/incidents/{incident_id}/close", json={"status": "banana"})
    assert resp.status_code == 400, resp.text
