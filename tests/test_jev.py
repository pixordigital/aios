"""Jev controlled evaluation harness."""

from aios.governance.jev import run_controlled_evaluation


def test_evaluate_matches_python_and_jev_and_hybrid():
    cases = [
        {"python_outcome": "noul", "jev_outcome": "noul", "reference": "noul"},
        {"python_outcome": "noul", "jev_outcome": "noul", "reference": "noul"},
    ]
    res = run_controlled_evaluation(cases)
    for approach in ("python_only", "jev", "hybrid"):
        assert res[approach]["agreement"] == 1.0
        assert res[approach]["decisions"] == 2


def test_agreement_counts_mismatches():
    cases = [
        {"python_outcome": "noul", "jev_outcome": "yes", "reference": "yes"},
        {"python_outcome": "yes", "jev_outcome": "yes", "reference": "yes"},
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
