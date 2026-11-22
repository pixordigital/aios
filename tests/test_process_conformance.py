"""Process conformance: deterministic deviation checks."""

import pytest

from aios.governance.process_conformance import check_conformance


def test_clean_run_has_no_deviation():
    dev, findings = check_conformance(
        steps_expected=["a", "b"],
        steps_executed=["a", "b"],
        approvals_required=0,
        approvals_done=0,
        outputs_valid=True,
    )
    assert dev is None
    assert findings == []


def test_skipped_step_is_execution_deviation():
    dev, findings = check_conformance(
        steps_expected=["a", "b"],
        steps_executed=["a"],
        approvals_required=0,
        approvals_done=0,
        outputs_valid=True,
    )
    assert dev == "execution_deviation"
    assert "skipped steps" in findings[0]


def test_missing_approval_is_policy_violation():
    dev, findings = check_conformance(
        steps_expected=["a"],
        steps_executed=["a"],
        approvals_required=1,
        approvals_done=0,
        outputs_valid=True,
    )
    assert dev == "policy_violation"


def test_tool_outside_allowlist_is_policy_violation():
    dev, _ = check_conformance(
        steps_expected=["a"],
        steps_executed=["a"],
        approvals_required=0,
        approvals_done=0,
        tools_allowed=["crm_update"],
        tools_used=["crm_update", "delete_customer"],
        outputs_valid=True,
    )
    assert dev == "policy_violation"


def test_invalid_output_is_execution_deviation():
    dev, _ = check_conformance(
        steps_expected=["a"],
        steps_executed=["a"],
        approvals_required=0,
        approvals_done=0,
        outputs_valid=False,
    )
    assert dev == "execution_deviation"


def test_limit_exceeded_is_policy_violation():
    dev, findings = check_conformance(
        steps_expected=["a"],
        steps_executed=["a"],
        approvals_required=0,
        approvals_done=0,
        limits_exceeded=True,
        outputs_valid=True,
    )
    assert dev == "policy_violation"
    assert "limit exceeded" in findings


def test_un_escalated_exception_is_execution_deviation():
    dev, _ = check_conformance(
        steps_expected=["a"],
        steps_executed=[],
        approvals_required=0,
        approvals_done=0,
        exception_occurred=True,
        escalated=False,
        outputs_valid=True,
    )
    assert dev == "execution_deviation"
