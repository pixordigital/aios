"""Lean Startup rules: declared thresholds decide, not enthusiasm."""

from datetime import datetime, timedelta

from aios.governance.innovation import (
    Experiment,
    decide_from_result,
    evaluate_experiment,
    innovation_scoreboard,
    missing_experiment_fields,
    over_budget,
)


def _exp(**overrides):
    data = dict(
        org_id="o", title="t", hypothesis_id="h1", riskiest_assumption="a",
        metric_name="meetings", baseline=0.0, sample_size=30,
        success_threshold=5.0, cost_cap_brl=100.0, time_cap_days=14,
        owner_id="u1", stop_conditions="no meetings after 50 sends",
        direction="increase",
    )
    data.update(overrides)
    return Experiment(**data)


def test_missing_fields_are_detected():
    exp = _exp(stop_conditions="")
    assert "stop_conditions" in missing_experiment_fields(exp)
    assert missing_experiment_fields(_exp()) == []


def test_threshold_pass_fail_is_deterministic():
    assert evaluate_experiment(_exp(observed=6)) == "success"
    assert evaluate_experiment(_exp(observed=4)) == "failure"
    assert evaluate_experiment(_exp(observed=4, direction="decrease", success_threshold=5)) == "success"
    assert evaluate_experiment(_exp()) == "pending"


def test_budget_breach_stops_experiment():
    exp = _exp(spent_brl=101)
    assert over_budget(exp)
    assert evaluate_experiment(exp) == "stopped"


def test_decision_mapping():
    assert decide_from_result("success") == "persevere"
    assert decide_from_result("failure") == "pivot"
    assert decide_from_result("stopped") == "stop"
    assert decide_from_result("pending") == "iterate"


def test_scoreboard_counts_validated_learning_not_features():
    t0 = datetime(2026, 11, 1)
    done = _exp(result="success", spent_brl=50, started_at=t0, ended_at=t0 + timedelta(days=4))
    failed = _exp(result="failure", spent_brl=50, started_at=t0, ended_at=t0 + timedelta(days=6))
    running = _exp(result="pending", spent_brl=10)
    board = innovation_scoreboard([done, failed, running])
    assert board["experiments"] == 3
    assert board["finished"] == 2
    assert board["validated"] == 1
    assert board["validation_rate"] == 0.5
    assert board["mean_cycle_days"] == 5.0
    assert board["cost_per_validated_brl"] == 110.0
