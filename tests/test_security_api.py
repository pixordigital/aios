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


async def test_cross_tenant_incident_access_records_metric(auth_client, test_db_session, second_org):
    from sqlalchemy import select
    from aios.governance.security import SecurityEvent, SecurityIncident

    other = SecurityIncident(
        org_id=second_org.id,
        incident_key="other-inc-1",
        title="Other org incident",
        severity="low",
        status="detected",
    )
    test_db_session.add(other)
    await test_db_session.commit()
    await test_db_session.refresh(other)

    resp = await auth_client.post(f"/api/security/incidents/{other.id}/respond", json={"action": "preserve_logs"})
    assert resp.status_code == 404, resp.text

    rows = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        )
    ).scalars().all()
    assert any(
        e.payload.get("metric") == "cross_tenant_block"
        and e.payload.get("resource_type") == "SecurityIncident"
        and e.payload.get("resource_org_id") == second_org.id
        and e.payload.get("incident_id") == other.id
        and e.source == "security.api.respond"
        for e in rows
    )


async def test_cross_tenant_event_ingest_records_metric(auth_client, test_db_session, second_org):
    from sqlalchemy import select
    from aios.governance.security import SecurityEvent, SecurityIncident

    other = SecurityIncident(
        org_id=second_org.id,
        incident_key="other-inc-2",
        title="Other org incident 2",
        severity="low",
        status="detected",
    )
    test_db_session.add(other)
    await test_db_session.commit()
    await test_db_session.refresh(other)

    resp = await auth_client.post(
        "/api/security/events",
        json={"event_type": "security.auth.failure", "incident_id": other.id, "payload": {"x": 1}},
    )
    assert resp.status_code == 404, resp.text

    rows = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        )
    ).scalars().all()
    assert any(
        e.payload.get("incident_id") == other.id
        and e.source == "security.api.event_ingest"
        and e.payload.get("resource_type") == "SecurityIncident"
        for e in rows
    )


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
    body = ing.json()
    assert body["stored"] is True
    assert body["metric"] is None
    listed = await auth_client.get(f"/api/security/events?incident_id={incident_id}")
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert any(i["event_type"] == "security.unauthorized_attempt" for i in items)


async def test_security_metric_ingest_and_metrics(auth_client):
    created = await auth_client.post("/api/security/incidents", json={"title": "MetricEvt", "severity": "low"})
    incident_id = created.json()["id"]

    for metric, payload in [
        ("auth_failure", {"ip": "1.2.3.4"}),
        ("cross_tenant_block", {"target_org": "other"}),
        ("recovery_drill", {"success": True}),
        ("false_positive", {"reason": "benign"}),
        ("vuln_reported", {"vuln_id": "CVE-TEST-1", "critical": True}),
        ("vuln_resolved", {"vuln_id": "CVE-TEST-1", "critical": True}),
    ]:
        resp = await auth_client.post(
            "/api/security/events",
            json={"metric": metric, "incident_id": incident_id, "payload": payload},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["metric"] == metric

    bad = await auth_client.post("/api/security/events", json={"metric": "not_a_metric"})
    assert bad.status_code == 400, bad.text

    metrics = await auth_client.get("/api/security/metrics")
    assert metrics.status_code == 200, metrics.text
    m = metrics.json()
    assert m["unauthorized_attempts"] >= 1
    assert m["cross_tenant_violations"] >= 1
    assert m["false_positive_rate"] is not None
    assert m["recovery_test_success_rate"] == 1.0
    assert m["unresolved_critical_vulns"] == 0
    assert m["metric_sources"]["unresolved_critical_vulns"] == "security_events.vuln_reported/vuln_resolved"
    assert m["coverage"]["recovery_test_events"] >= 1
    assert m["coverage"]["false_positive_events"] >= 1


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


async def _make_founder(test_org, test_user, test_db_session):
    test_org.extra_data = {**(test_org.extra_data or {}), "founder_user_id": test_user.id}
    await test_db_session.commit()
    await test_db_session.refresh(test_org)


async def test_preapprovals_require_founder(auth_client):
    resp = await auth_client.get("/api/security/preapprovals")
    assert resp.status_code == 403, resp.text


async def test_preapprovals_crud_and_respond_authorization(auth_client, test_org, test_user, test_db_session):
    await _make_founder(test_org, test_user, test_db_session)

    got = await auth_client.get("/api/security/preapprovals")
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["preapproved_actions"] == []
    assert body["approvals"] == []
    assert "shared app DB" in body["storage"]

    put = await auth_client.put(
        "/api/security/preapprovals",
        json={"preapproved_actions": ["rotate_credential"], "approvals": [{"id": "a1", "action": "disable_integration", "approved": True, "ticket": "SEC-1"}]},
    )
    assert put.status_code == 200, put.text
    pbody = put.json()
    assert pbody["preapproved_actions"] == ["rotate_credential"]
    assert pbody["approvals"][0]["ticket"] == "SEC-1"

    add = await auth_client.post("/api/security/preapprovals/actions", json={"action": "isolate_container"})
    assert add.status_code == 200, add.text
    assert "isolate_container" in add.json()["preapproved_actions"]

    rm = await auth_client.delete("/api/security/preapprovals/actions/isolate_container")
    assert rm.status_code == 200, rm.text
    assert "isolate_container" not in rm.json()["preapproved_actions"]

    rec = await auth_client.post(
        "/api/security/preapprovals/approvals",
        json={"id": "a2", "action": "restrict_db_route", "approved": True},
    )
    assert rec.status_code == 200, rec.text
    assert any(r["id"] == "a2" for r in rec.json()["approvals"])

    del_rec = await auth_client.delete("/api/security/preapprovals/approvals/a2")
    assert del_rec.status_code == 200, del_rec.text
    assert all(r.get("id") != "a2" for r in del_rec.json()["approvals"])

    created = await auth_client.post("/api/security/incidents", json={"title": "Cred leak", "severity": "high"})
    incident_id = created.json()["id"]
    resp = await auth_client.post(
        f"/api/security/incidents/{incident_id}/respond",
        json={"action": "rotate_credential"},
    )
    assert resp.status_code == 200, resp.text
    rbody = resp.json()
    assert rbody["allowed"] is True
    assert rbody["level"] == "conditional"
    assert rbody["preapproval_source"] == "security_policy.preapproved_actions"

    events = await auth_client.get("/api/security/events?event_type=security.policy.preapprovals_updated")
    assert events.status_code == 200, events.text
    assert len(events.json()["items"]) >= 1


async def test_preapprovals_reject_unknown_action(auth_client, test_org, test_user, test_db_session):
    await _make_founder(test_org, test_user, test_db_session)
    bad = await auth_client.post("/api/security/preapprovals/actions", json={"action": "launch_missiles"})
    assert bad.status_code == 400, bad.text
    bad_put = await auth_client.put("/api/security/preapprovals", json={"preapproved_actions": ["delete_data_typo"]})
    assert bad_put.status_code == 400, bad_put.text


async def test_preapproval_record_authorizes_respond(auth_client, test_org, test_user, test_db_session):
    await _make_founder(test_org, test_user, test_db_session)
    rec = await auth_client.post(
        "/api/security/preapprovals/approvals",
        json={"id": "rec-1", "action": "disable_integration", "approved": True, "ticket": "SEC-42"},
    )
    assert rec.status_code == 200, rec.text

    created = await auth_client.post("/api/security/incidents", json={"title": "Integration anomaly", "severity": "medium"})
    incident_id = created.json()["id"]
    resp = await auth_client.post(f"/api/security/incidents/{incident_id}/respond", json={"action": "disable_integration"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["allowed"] is True
    assert body["preapproval_source"] == "rec-1"

    rm = await auth_client.delete("/api/security/preapprovals/approvals/rec-1")
    assert rm.status_code == 200, rm.text
    created2 = await auth_client.post("/api/security/incidents", json={"title": "Integration anomaly 2", "severity": "medium"})
    incident2 = created2.json()["id"]
    resp2 = await auth_client.post(f"/api/security/incidents/{incident2}/respond", json={"action": "disable_integration"})
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["allowed"] is False


async def test_login_failure_records_auth_metric(async_client, auth_client, test_user):
    resp = await async_client.post(
        "/api/auth/login",
        json={"email": test_user.email, "password": "wrong-password"},
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "E-mail ou senha inválidos"

    events = await auth_client.get("/api/security/events?event_type=security.auth.failure")
    assert events.status_code == 200, events.text
    items = events.json()["items"]
    assert any(
        i.get("payload", {}).get("reason") == "invalid_credentials"
        and i.get("payload", {}).get("source") == "auth.login"
        and i.get("actor_id") == test_user.id
        for i in items
    )

    metrics = await auth_client.get("/api/security/metrics")
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["unauthorized_attempts"] >= 1


async def test_bearer_allowlist_reject_records_auth_metric(auth_client, test_user, test_db_session, monkeypatch):
    from aios.config import settings
    from sqlalchemy import select
    from aios.governance.security import SecurityEvent

    monkeypatch.setattr(settings, "login_allowlist", "someone-else@example.com")
    resp = await auth_client.get("/api/agents")
    assert resp.status_code == 401, resp.text

    rows = (await test_db_session.execute(
        select(SecurityEvent).where(SecurityEvent.event_type == "security.auth.failure")
    )).scalars().all()
    assert any(
        e.actor_id == test_user.id
        and e.org_id == test_user.org_id
        and (e.payload or {}).get("reason") == "allowlist_denied"
        and (e.payload or {}).get("source") == "api.deps.get_current_user"
        for e in rows
    )


async def test_dashboard_cookie_allowlist_reject_records_auth_metric(async_client, test_user, test_db_session, monkeypatch):
    from aios.api.deps import COOKIE_NAME, create_jwt_token
    from aios.config import settings
    from sqlalchemy import select
    from aios.governance.security import SecurityEvent

    token = create_jwt_token(test_user.id, test_user.org_id)
    async_client.cookies.set(COOKIE_NAME, token)
    monkeypatch.setattr(settings, "login_allowlist", "someone-else@example.com")
    resp = await async_client.get("/api/agents")
    assert resp.status_code == 401, resp.text

    rows = (await test_db_session.execute(
        select(SecurityEvent).where(SecurityEvent.event_type == "security.auth.failure")
    )).scalars().all()
    assert any(
        e.actor_id == test_user.id
        and e.org_id == test_user.org_id
        and (e.payload or {}).get("reason") == "allowlist_denied"
        and (e.payload or {}).get("source") == "api.deps.get_dashboard_user"
        for e in rows
    )


async def test_refresh_allowlist_reject_records_auth_metric(async_client, test_user, test_db_session, monkeypatch):
    from aios.config import settings
    from sqlalchemy import select
    from aios.governance.security import SecurityEvent

    login = await async_client.post("/api/auth/login", json={"email": test_user.email, "password": "testpass123"})
    assert login.status_code == 200, login.text
    refresh_token = login.json()["refresh_token"]

    monkeypatch.setattr(settings, "login_allowlist", "someone-else@example.com")
    resp = await async_client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 401, resp.text

    rows = (await test_db_session.execute(
        select(SecurityEvent).where(SecurityEvent.event_type == "security.auth.failure")
    )).scalars().all()
    assert any(
        e.actor_id == test_user.id
        and e.org_id == test_user.org_id
        and (e.payload or {}).get("reason") == "allowlist_denied"
        and (e.payload or {}).get("source") == "auth.refresh"
        for e in rows
    )


async def test_refresh_unknown_jti_records_auth_metric(async_client, test_user, test_db_session):
    from aios.api.auth import _create_jwt_token
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from aios.governance.security import SecurityEvent

    token, _ = _create_jwt_token(
        {
            "sub": test_user.id,
            "jti": "missing-jti",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
        },
        token_type="refresh",
    )
    resp = await async_client.post("/api/auth/refresh", json={"refresh_token": token})
    assert resp.status_code == 401, resp.text

    rows = (await test_db_session.execute(
        select(SecurityEvent).where(SecurityEvent.event_type == "security.auth.failure")
    )).scalars().all()
    assert any(
        e.actor_id == test_user.id
        and e.org_id == test_user.org_id
        and (e.payload or {}).get("reason") == "refresh_unknown_jti"
        and (e.payload or {}).get("source") == "auth.refresh"
        for e in rows
    )
