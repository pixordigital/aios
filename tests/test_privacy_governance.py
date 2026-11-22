"""LGPD enforcement: fail closed, purpose-bound, tenant-scoped."""

from datetime import datetime

from aios.governance.privacy import (
    ProcessingActivity,
    deletion_targets,
    evaluate_processing,
    request_due_at,
    ripd_required,
)


def _activity(**overrides):
    data = dict(
        org_id="t1",
        activity_key="lia_outreach",
        purpose="sales outreach",
        legal_basis="legitimate_interest",
        legal_basis_evidence="LIA-2026-01",
        necessity_assessment="minimal contact fields only",
        status="approved",
        sensitive_data=False,
        international_transfers=[],
        transfer_mechanism="",
    )
    data.update(overrides)
    return ProcessingActivity(**data)


def _eval(activity, **kw):
    kw.setdefault("action", "read")
    return evaluate_processing(
        activity, actor_org_id="t1", tenant_org_id="t1", **kw
    )[0]


def test_cross_tenant_is_denied():
    outcome, reason = evaluate_processing(
        _activity(), actor_org_id="t2", tenant_org_id="t1", action="read"
    )
    assert outcome == "deny"
    assert "tenant" in reason


def test_missing_record_is_denied():
    assert _eval(None) == "deny"


def test_unapproved_activity_is_denied():
    assert _eval(_activity(status="draft")) == "deny"


def test_sensitive_without_policy_fails_closed():
    assert _eval(_activity(sensitive_data=True), policy_available=False) == "deny"
    assert _eval(_activity(), policy_available=False) == "defer"


def test_legitimate_interest_needs_evidence_and_cannot_cover_sensitive():
    assert _eval(_activity(legal_basis_evidence="")) == "deny"
    assert _eval(_activity(legal_basis_evidence="x", sensitive_data=True)) == "deny"


def test_purpose_mismatch_restricts():
    assert _eval(_activity(), purpose="payroll") == "restrict"


def test_opt_out_blocks_outreach():
    assert _eval(_activity(), action="outreach", opt_out=True) == "deny"


def test_legal_hold_blocks_deletion():
    assert _eval(_activity(), action="delete", legal_hold=True) == "restrict"


def test_transfer_without_mechanism_requires_approval():
    assert _eval(_activity(international_transfers=["us-vendor"])) == "require_approval"


def test_missing_necessity_requires_approval():
    assert _eval(_activity(necessity_assessment="")) == "require_approval"


def test_happy_path_allows():
    assert _eval(_activity()) == "allow"


def test_request_due_and_deletion_targets():
    start = datetime(2026, 11, 22)
    assert (request_due_at(start) - start).days == 15
    assert ripd_required(sensitive_data=True, large_scale=False, high_risk=False)
    assert not ripd_required(sensitive_data=False, large_scale=False, high_risk=False)
    assert "embeddings" in deletion_targets()
    assert "vendors" in deletion_targets()
