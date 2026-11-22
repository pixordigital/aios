"""Solution-Fit: no opportunity score excuses infeasibility or weak evidence."""

from aios.governance.capability_registry import (
    Capability,
    capability_fit_score,
    next_stage,
    solution_fit,
)

GOOD = dict(
    problem_fit=0.8,
    feasibility=0.8,
    commercial_viability=0.8,
    buying_readiness=0.8,
    evidence_confidence=0.8,
)


def _cap(maturity="production", available=True, evidence=None, use_cases=("lead_ops",)):
    return Capability(
        org_id="o",
        capability_key="k",
        name="n",
        maturity=maturity,
        is_commercially_available=available,
        deployment_evidence=evidence or [],
        supported_use_cases=list(use_cases),
    )


def test_high_problem_fit_cannot_compensate_for_immature_capability():
    assert solution_fit(_cap("concept", False), **GOOD)[0] == "future_opportunity"
    assert solution_fit(_cap("prototype", False), **GOOD)[0] == "future_opportunity"


def test_weak_evidence_requires_research_even_with_high_fit():
    kw = dict(GOOD, evidence_confidence=0.2)
    assert solution_fit(_cap(), **kw)[0] == "research_required"


def test_infeasible_is_disqualified():
    kw = dict(GOOD, feasibility=0.1)
    assert solution_fit(_cap(), **kw)[0] == "disqualified"


def test_prohibited_contact_is_restricted():
    assert solution_fit(_cap(), contact_allowed=False, **GOOD)[0] == "restricted"


def test_not_ready_to_buy_is_nurtured():
    kw = dict(GOOD, buying_readiness=0.2)
    assert solution_fit(_cap(), **kw)[0] == "nurture"


def test_all_dimensions_strong_is_qualified():
    assert solution_fit(_cap(), **GOOD)[0] == "qualified"


def test_missing_capability_requires_research():
    assert solution_fit(None, **GOOD)[0] == "research_required"


def test_capability_fit_score():
    assert capability_fit_score(_cap("production"), "lead_ops") > capability_fit_score(_cap("pilot"), "lead_ops")
    assert capability_fit_score(_cap("production"), "unknown") == 0.0
    assert capability_fit_score(_cap("deprecated"), "lead_ops") == 0.0


def test_pipeline_stage_order():
    assert next_stage("company_discovery") == "prospect_intelligence"
    assert next_stage("outcome_feedback") is None
    assert next_stage("bogus") is None
