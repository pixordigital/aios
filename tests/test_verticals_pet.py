"""Pet-business vertical: profile, contract and policy gates."""

import pytest

from aios.verticals.pet_business import (
    OutcomeCounts,
    PetBusinessProfile,
    WORKFLOW_CONTRACTS,
    contract_for,
    may_follow_up,
    requires_human,
    summarize_outcomes,
)
from aios.verticals.pet_business.workflows import has_contract, paid_workflow_class

PROFILE = {
    "business_name": "Pet Shop Teste",
    "services": [
        {"name": "Banho", "price_brl": 60.0, "duration_minutes": 45},
        {"name": "Ração 10kg"},
    ],
    "hours": {"mon": "09:00-18:00", "sun": "closed"},
    "escalation_rules": {"veterinário": "vet_on_call", "reclamação": "manager"},
}


def test_profile_loads_and_validates():
    profile = PetBusinessProfile.from_dict(PROFILE)
    assert profile.validate() == []
    assert list(profile.service_names()) == ["Banho", "Ração 10kg"]
    # An unapproved price stays None instead of becoming a made-up number.
    assert profile.services[1].price_brl is None


def test_profile_requires_commercial_facts():
    with pytest.raises(ValueError, match="missing"):
        PetBusinessProfile.from_dict({"services": []})


def test_profile_validation_reports_gaps():
    profile = PetBusinessProfile(
        business_name="Pet Shop Teste",
        services=(),
        hours={},
        escalation_rules={},
    )
    assert "no escalation rules configured" in profile.validate()


def test_every_paid_workflow_has_a_contract():
    assert set(WORKFLOW_CONTRACTS) == {"pet_lead_capture", "pet_lead_follow_up"}
    for name in WORKFLOW_CONTRACTS:
        assert has_contract(name)
    assert contract_for("pet_lead_follow_up").approval_required is True
    assert "execute_code" in contract_for("pet_lead_capture").denied_tools


def test_paid_workflow_class_reads_only_declared_values():
    assert paid_workflow_class({"workflow_class": "pet_lead_capture"}) == "pet_lead_capture"
    assert paid_workflow_class({"workflow_class": ""}) is None
    assert paid_workflow_class(None) is None


def test_opt_out_beats_cadence():
    profile = PetBusinessProfile.from_dict(PROFILE)
    decision = may_follow_up(profile, customer_text="pode parar", follow_ups_sent=0)
    assert decision.allowed is False
    assert "opted out" in decision.reason


def test_follow_up_cap_and_interval():
    profile = PetBusinessProfile.from_dict(PROFILE)
    assert may_follow_up(
        profile, follow_ups_sent=0, hours_since_last_contact=1
    ).allowed is False
    assert may_follow_up(
        profile, follow_ups_sent=2, hours_since_last_contact=48
    ).allowed is False
    assert may_follow_up(
        profile, follow_ups_sent=1, hours_since_last_contact=48
    ).allowed is True


def test_escalation_matches_profile_rule():
    profile = PetBusinessProfile.from_dict(PROFILE)
    assert requires_human(profile, "meu cachorro passou no veterinário") == (
        True,
        "vet_on_call",
    )
    assert requires_human(profile, "quero banho amanhã") == (False, None)


def test_outcome_summary_keeps_attribution_label():
    summary = summarize_outcomes(
        OutcomeCounts(
            enquiries=10,
            answered=8,
            qualified_leads=4,
            follow_ups_attempted=4,
            follow_ups_completed=3,
            deals_attributed=2,
            attributed_value_brl=350.0,
            human_handoffs=1,
        ),
        attribution_source="crm_deal.agent_id",
        attribution_confidence="medium",
    )
    assert summary["answered_pct"] == 80.0
    assert summary["unanswered"] == 2
    assert summary["attribution_confidence"] == "medium"
    assert summary["attributed_value_brl"] == 350.0
