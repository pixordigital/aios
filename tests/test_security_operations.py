"""AI SOC: response authority, severity, privacy handoff and metrics."""

from datetime import datetime, timedelta

import pytest

from fastapi import HTTPException

from aios.api.deps import verify_org_access, verify_org_access_async
from aios.governance.security import (
    SecurityEvent,
    SecurityIncident,
    check_response,
    classify_severity,
    derive_actor_type,
    emit_security_metric_event,
    incident_metrics,
    record_auth_failure,
    record_cross_tenant_block,
    record_cross_tenant_block_if_mismatch,
    record_false_positive,
    record_recovery_drill,
    record_vuln_reported,
    record_vuln_resolved,
    require_privacy_handoff,
    response_authority,
    stored_preapproval,
)


def test_unknown_action_fails_closed_to_human():
    assert response_authority("launch_missiles") == "human"


def test_autonomous_containment_allowed():
    ok, _ = check_response("preserve_logs", actor_type="agent")
    assert ok
    ok, _ = check_response("pause_suspicious_agent", actor_type="agent")
    assert ok


def test_conditional_needs_preapproved_human():
    assert not check_response("rotate_credential", actor_type="agent", preapproved=True)[0]
    assert not check_response("rotate_credential", actor_type="human", preapproved=False)[0]
    assert check_response("rotate_credential", actor_type="human", preapproved=True)[0]


def test_destructive_requires_founder():
    assert not check_response("delete_data", actor_type="human", preapproved=True)[0]
    assert check_response("delete_data", actor_type="human", founder=True)[0]


def test_severity_classification():
    assert classify_severity(cross_tenant=True, credential_exposure=False, personal_data=False, confirmed_impact=False) == "critical"
    assert classify_severity(cross_tenant=False, credential_exposure=True, personal_data=False, confirmed_impact=False) == "high"
    assert classify_severity(cross_tenant=False, credential_exposure=False, personal_data=False, confirmed_impact=False) == "low"


def test_privacy_handoff_is_recorded_once():
    inc = SecurityIncident(org_id="o", incident_key="i", title="t", personal_data_involved=True)
    assert require_privacy_handoff(inc)
    assert inc.privacy_handoff_at is not None
    assert not require_privacy_handoff(inc)


def test_incident_metrics():
    t0 = datetime(2026, 11, 22, 10, 0)
    inc = SecurityIncident(
        org_id="o", incident_key="i", title="t", severity="critical",
        detected_at=t0, acknowledged_at=t0 + timedelta(minutes=5),
        contained_at=t0 + timedelta(minutes=20),
        recovered_at=t0 + timedelta(minutes=60),
    )
    ev = SecurityEvent(org_id="o", source="gw", event_type="security.unauthorized_attempt", payload={})
    m = incident_metrics([inc], events=[ev])
    assert m["incidents"] == 1
    assert m["critical_open"] == 1
    assert m["mttd_minutes"] == 5.0
    assert m["mtta_minutes"] == 5.0
    assert m["mttr_minutes"] == 60.0
    assert m["mean_detect_minutes"] == 5.0
    assert m["mean_contain_minutes"] == 15.0
    assert m["mean_recover_minutes"] == 40.0
    assert m["unauthorized_attempts"] == 1
    assert m["cross_tenant_violations"] == 0
    assert m["unresolved_critical_vulns"] is None
    assert m["metric_sources"]["unresolved_critical_vulns"].startswith("unknown:")


def test_derive_actor_type_deterministic():
    class U:
        id = "u1"
        role = "member"
    class O:
        extra_data = {}
    assert derive_actor_type(user=U(), org=O()) == "human"


def test_stored_preapproval_requires_policy_record():
    class O:
        extra_data = {"security_policy": {"preapproved_actions": ["rotate_credential"]}}
    ok, src = stored_preapproval(action="rotate_credential", org=O(), actor_type="human")
    assert ok is True
    assert src == "security_policy.preapproved_actions"
    ok2, _ = stored_preapproval(action="disable_integration", org=O(), actor_type="human")
    assert ok2 is False


class _FakeDB:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.added = []

    def add(self, obj):
        if self.fail:
            raise RuntimeError("boom")
        self.added.append(obj)

    async def flush(self):
        if self.fail:
            raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_metric_producers_record_deterministic_events():
    db = _FakeDB()
    await record_auth_failure(db, org_id="o1", actor_id="u1", payload={"ip": "1.2.3.4"})
    await record_cross_tenant_block(db, org_id="o1", payload={"target_org": "o2"})
    await record_recovery_drill(db, org_id="o1", success=True, payload={"drill": "backup"})
    await record_false_positive(db, org_id="o1", incident_id="i1")
    await record_vuln_reported(db, org_id="o1", vuln_id="CVE-1", critical=True)
    await record_vuln_resolved(db, org_id="o1", vuln_id="CVE-1", critical=True)

    types = [e.event_type for e in db.added]
    assert types == [
        "security.auth.failure",
        "security.cross_tenant.blocked",
        "security.recovery.drill",
        "security.detection.false_positive",
        "security.vuln.reported",
        "security.vuln.resolved",
    ]
    assert db.added[0].payload["metric"] == "auth_failure"
    assert db.added[2].payload["success"] is True
    assert db.added[4].payload["vuln_id"] == "CVE-1"


@pytest.mark.asyncio
async def test_metric_producers_best_effort_no_crash():
    db = _FakeDB(fail=True)
    assert await record_auth_failure(db, org_id="o1") is None
    assert await emit_security_metric_event(db, org_id="o1", metric="custom", source="test") is None


@pytest.mark.asyncio
async def test_record_cross_tenant_block_if_mismatch():
    db = _FakeDB()

    class R:
        org_id = "other-org"
        id = "r1"

    evt = await record_cross_tenant_block_if_mismatch(
        db,
        org_id="org-a",
        resource=R(),
        source="api.test",
        actor_type="human",
        actor_id="u1",
        payload={"incident_id": "i1"},
    )
    assert evt is not None
    assert len(db.added) == 1
    payload = db.added[0].payload
    assert db.added[0].event_type == "security.cross_tenant.blocked"
    assert payload["metric"] == "cross_tenant_block"
    assert payload["requested_org_id"] == "org-a"
    assert payload["resource_org_id"] == "other-org"
    assert payload["resource_type"] == "R"
    assert payload["incident_id"] == "i1"

    assert await record_cross_tenant_block_if_mismatch(db, org_id="org-a", resource=None) is None
    assert len(db.added) == 1

    class Same:
        org_id = "org-a"

    assert await record_cross_tenant_block_if_mismatch(db, org_id="org-a", resource=Same()) is None
    assert len(db.added) == 1


def test_incident_metrics_from_metric_producers():
    evs = [
        SecurityEvent(org_id="o", source="auth", event_type="security.auth.failure", payload={}),
        SecurityEvent(org_id="o", source="tenant", event_type="security.cross_tenant.blocked", payload={}),
        SecurityEvent(org_id="o", source="detect", event_type="security.detection.false_positive", payload={}),
        SecurityEvent(org_id="o", source="drill", event_type="security.recovery.drill", payload={"success": True}),
        SecurityEvent(org_id="o", source="drill", event_type="security.recovery.drill", payload={"success": False}),
        SecurityEvent(org_id="o", source="vuln", event_type="security.vuln.reported", payload={"vuln_id": "V1", "critical": True}),
        SecurityEvent(org_id="o", source="vuln", event_type="security.vuln.reported", payload={"vuln_id": "V2", "critical": False}),
        SecurityEvent(org_id="o", source="vuln", event_type="security.vuln.resolved", payload={"vuln_id": "V1", "critical": True}),
    ]
    m = incident_metrics([], events=evs)
    assert m["unauthorized_attempts"] == 1
    assert m["cross_tenant_violations"] == 1
    assert m["false_positive_rate"] == 1.0
    assert m["recovery_test_success_rate"] == 0.5
    assert m["unresolved_critical_vulns"] == 0
    assert m["coverage"]["false_positive_events"] == 1
    assert m["coverage"]["recovery_test_events"] == 2
    assert m["coverage"]["vuln_events"] == 3
    assert m["metric_sources"]["unresolved_critical_vulns"] == "security_events.vuln_reported/vuln_resolved"


def test_verify_org_access_sync_preserves_404_semantics():
    class R:
        org_id = "org-a"
        id = "r1"

    verify_org_access("org-a", R())
    with pytest.raises(HTTPException) as exc_missing:
        verify_org_access("org-a", None)
    assert exc_missing.value.status_code == 404
    with pytest.raises(HTTPException) as exc_mismatch:
        verify_org_access("org-a", type("R2", (), {"org_id": "org-b"})())
    assert exc_mismatch.value.status_code == 404


@pytest.mark.asyncio
async def test_verify_org_access_async_records_cross_tenant_mismatch():
    db = _FakeDB()

    class R:
        org_id = "org-b"
        id = "r1"

    with pytest.raises(HTTPException) as exc:
        await verify_org_access_async(
            "org-a",
            R(),
            db=db,
            actor_id="u1",
            actor_type="human",
            source="api.test.verify_org_access",
            payload={"endpoint": "/x"},
        )
    assert exc.value.status_code == 404
    assert len(db.added) == 1
    evt = db.added[0]
    assert evt.event_type == "security.cross_tenant.blocked"
    assert evt.payload["requested_org_id"] == "org-a"
    assert evt.payload["resource_org_id"] == "org-b"
    assert evt.payload["endpoint"] == "/x"
    assert evt.actor_id == "u1"
    assert evt.actor_type == "human"


@pytest.mark.asyncio
async def test_verify_org_access_async_no_metric_on_same_org_or_missing():
    db = _FakeDB()

    class R:
        org_id = "org-a"

    await verify_org_access_async("org-a", R(), db=db, actor_id="u1")
    assert db.added == []

    with pytest.raises(HTTPException):
        await verify_org_access_async("org-a", None, db=db, actor_id="u1")
    assert db.added == []


@pytest.mark.asyncio
async def test_verify_org_access_async_metric_failure_still_404():
    db = _FakeDB(fail=True)

    class R:
        org_id = "org-b"

    with pytest.raises(HTTPException) as exc:
        await verify_org_access_async("org-a", R(), db=db, actor_id="u1")
    assert exc.value.status_code == 404
