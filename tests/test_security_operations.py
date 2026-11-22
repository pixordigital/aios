"""AI SOC: response authority, severity, privacy handoff and metrics."""

from datetime import datetime, timedelta

from aios.governance.security import (
    SecurityIncident,
    check_response,
    classify_severity,
    incident_metrics,
    require_privacy_handoff,
    response_authority,
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
    m = incident_metrics([inc])
    assert m["incidents"] == 1
    assert m["critical_open"] == 1
    assert m["mean_detect_minutes"] == 5.0
    assert m["mean_contain_minutes"] == 15.0
    assert m["mean_recover_minutes"] == 40.0
