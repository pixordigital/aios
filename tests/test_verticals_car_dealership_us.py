"""Car-dealership (US) vertical: profile, contract and policy gates."""

import pytest

from aios.verticals.car_dealership_us import (
    CarDealershipUSProfile,
    OutcomeCounts,
    WORKFLOW_CONTRACTS,
    contract_for,
    may_follow_up,
    requires_human,
    summarize_outcomes,
)
from aios.verticals.car_dealership_us.workflows import has_contract, paid_workflow_class

PROFILE = {
    "business_name": "Example Motors",
    "services": [
        {"name": "New vehicle sales", "price_usd": 35000.0},
        {"name": "Trade-in appraisal"},
    ],
    "hours": {"mon": "09:00-19:00", "sun": "closed"},
    "escalation_rules": {"lawyer": "general_manager", "financing complaint": "finance_manager"},
}


def test_profile_loads_and_validates():
    profile = CarDealershipUSProfile.from_dict(PROFILE)
    assert profile.validate() == []
    assert list(profile.service_names()) == ["New vehicle sales", "Trade-in appraisal"]
    # Unapproved price stays None, never invented.
    assert profile.services[1].price_usd is None


def test_profile_requires_commercial_facts():
    with pytest.raises(ValueError, match="missing"):
        CarDealershipUSProfile.from_dict({"services": []})


def test_profile_validation_reports_gaps():
    profile = CarDealershipUSProfile(
        business_name="Example Motors",
        services=(),
        hours={},
        escalation_rules={},
    )
    issues = profile.validate()
    assert "no services/offerings configured" in issues
    assert "no hours configured" in issues
    assert "no escalation rules configured" in issues


def test_every_paid_workflow_has_a_contract():
    assert set(WORKFLOW_CONTRACTS) == {
        "car_dealership_us_lead_capture",
        "car_dealership_us_lead_follow_up",
    }
    for name in WORKFLOW_CONTRACTS:
        assert has_contract(name)
    assert contract_for("car_dealership_us_lead_follow_up").approval_required is True
    assert "execute_code" in contract_for("car_dealership_us_lead_capture").denied_tools
    assert "make_voice_call" in contract_for("car_dealership_us_lead_follow_up").denied_tools


def test_paid_workflow_class_reads_only_declared_values():
    assert (
        paid_workflow_class({"workflow_class": "car_dealership_us_lead_capture"})
        == "car_dealership_us_lead_capture"
    )
    assert paid_workflow_class({"workflow_class": ""}) is None
    assert paid_workflow_class(None) is None
    assert paid_workflow_class("not-a-dict") is None


def test_opt_out_beats_cadence():
    profile = CarDealershipUSProfile.from_dict(PROFILE)
    decision = may_follow_up(profile, customer_text="please stop messaging me", follow_ups_sent=0)
    assert decision.allowed is False
    assert "opted out" in decision.reason


def test_follow_up_cap_and_interval():
    profile = CarDealershipUSProfile.from_dict(PROFILE)
    blocked_interval = may_follow_up(profile, follow_ups_sent=0, hours_since_last_contact=1)
    assert blocked_interval.allowed is False
    assert "minimum interval" in blocked_interval.reason

    blocked_cap = may_follow_up(profile, follow_ups_sent=2, hours_since_last_contact=48)
    assert blocked_cap.allowed is False
    assert "cap reached" in blocked_cap.reason

    allowed = may_follow_up(profile, follow_ups_sent=1, hours_since_last_contact=48)
    assert allowed.allowed is True
    assert allowed.reason == "allowed"


def test_escalation_matches_profile_rule():
    profile = CarDealershipUSProfile.from_dict(PROFILE)
    assert requires_human(profile, "I want to talk to my lawyer") == (True, "general_manager")
    assert requires_human(profile, "I have a financing complaint") == (True, "finance_manager")
    assert requires_human(profile, "I want to see SUVs tomorrow") == (False, None)


def test_outcome_summary_keeps_attribution_label():
    summary = summarize_outcomes(
        OutcomeCounts(
            enquiries=10,
            answered=8,
            qualified_leads=4,
            follow_ups_attempted=4,
            follow_ups_completed=3,
            deals_attributed=2,
            attributed_value=3500.0,
            human_handoffs=1,
            failed=1,
        ),
        attribution_source="crm_deal.agent_id",
        attribution_confidence="medium",
    )
    assert summary["answered_pct"] == 80.0
    assert summary["unanswered"] == 2
    assert summary["qualification_pct"] == 50.0
    assert summary["follow_up_completion_pct"] == 75.0
    assert summary["human_handoff_pct"] == 10.0
    assert summary["failure_pct"] == 10.0
    assert summary["attributed_value"] == 3500.0
    assert summary["attributed_value_brl"] == 3500.0
    assert summary["currency"] == "USD"
    assert summary["attribution_source"] == "crm_deal.agent_id"
    assert summary["attribution_confidence"] == "medium"
