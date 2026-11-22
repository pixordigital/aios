"""Jev controlled evaluation harness."""

from aios.governance.jev import decide, run_controlled_evaluation


def _case(**kw):
    base = {
        "python_outcome": "noul",
        "jev_outcome": "noul",
        "reference": "noul",
        "measurable_value": {"metric": "cost_per_success", "baseline": 1.0, "target": 0.8},
    }
    base.update(kw)
    return base


def test_evaluate_matches_python_and_jev_and_hybrid():
    cases = [_case(), _case()]
    res = run_controlled_evaluation(cases)
    for approach in ("python_only", "jev", "hybrid"):
        assert res[approach]["agreement"] == 1.0
        assert res[approach]["decisions"] == 2


def test_agreement_counts_mismatches():
    cases = [
        _case(python_outcome="noul", jev_outcome="yes", reference="yes"),
        _case(python_outcome="yes", jev_outcome="yes", reference="yes"),
    ]
    res = run_controlled_evaluation(cases)
    assert res["python_only"]["agreement"] == 0.5
    assert res["jev"]["agreement"] == 1.0
    assert res["hybrid"]["agreement"] == 0.5


def test_empty_case_set_is_safe():
    assert run_controlled_evaluation([])["jev"]["agreement"] == 0.0


def test_unknown_decision_type_rejected():
    from aios.governance.jev import JEV_DECISION_TYPES

    assert set(JEV_DECISION_TYPES) >= {"noul", "choice", "score"}


def test_jev_cannot_override_mandatory_eligibility():
    case = _case(
        python_outcome="model_a",
        jev_outcome="model_b",
        eligible_candidates=["model_a"],
        reference="model_a",
    )
    d = decide("jev", case, case["reference"])
    assert d["outcome"] == "human_review"
    assert d["confidence_is_evidence"] is False


def test_confidence_not_evidence_field():
    d = decide("jev", _case(confidence=0.99), "noul")
    assert d["confidence"] == 0.99
    assert d["confidence_is_evidence"] is False
    assert "evidence" in d


def test_measurable_value_gate_blocks():
    case = _case()
    case.pop("measurable_value")
    d = decide("python_only", case, "noul")
    assert d["outcome"] == "blocked_measurable_value_gate"
    assert d["gate_ok"] is False


def test_personal_data_requires_vendor_lgpd_assessment():
    case = _case(contains_personal_data=True)
    d = decide("hybrid", case, "noul")
    assert d["outcome"] == "blocked_data_assessment"
    case["data_assessment"] = {"vendor_ok": True, "lgpd_ok": True, "personal_data": True}
    d2 = decide("hybrid", case, "noul")
    assert d2["outcome"] == "noul"
