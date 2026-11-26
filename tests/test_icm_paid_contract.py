"""Paid workflows must be governed; internal opt-in ICM-X stays opt-in."""

from types import SimpleNamespace

import pytest

from aios.icm.agent_binding import ICMContractRequired, assert_paid_workflow_contract


def _agent(extra_data):
    return SimpleNamespace(id="a1", extra_data=extra_data)


def test_internal_agent_needs_no_contract():
    assert_paid_workflow_contract(_agent({}))
    assert_paid_workflow_contract(_agent(None))


def test_paid_workflow_without_icm_binding_is_refused():
    with pytest.raises(ICMContractRequired, match="extra_data\\['icm'\\]"):
        assert_paid_workflow_contract(
            _agent({"workflow_class": "car_dealership_us_lead_capture"})
        )


def test_unknown_paid_workflow_is_refused():
    with pytest.raises(ICMContractRequired, match="not owned by any vertical"):
        assert_paid_workflow_contract(
            _agent(
                {
                    "workflow_class": "made_up_paid_workflow",
                    "icm": {"workspace_id": "w", "stage_id": "s"},
                }
            )
        )


def test_paid_workflow_with_binding_passes():
    assert_paid_workflow_contract(
        _agent(
            {
                "workflow_class": "car_dealership_us_lead_capture",
                "icm": {"workspace_id": "cd_us_ops", "stage_id": "car_dealership_us_lead_capture"},
            }
        )
    )
