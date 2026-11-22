"""Lean Startup rules: declared thresholds decide, not enthusiasm."""

from datetime import datetime, timedelta

from aios.governance.innovation import (
    Experiment,
    decide_from_result,
    evaluate_experiment,
    innovation_scoreboard,
    is_track_c_autonomous,
    missing_experiment_fields,
    over_budget,
    production_promotion_allowed,
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


def test_hypothesis_linkage_or_justified_orphan_required():
    assert "hypothesis_id_or_orphan_justification" in missing_experiment_fields(_exp(hypothesis_id=None))
    justified = _exp(hypothesis_id=None, permissions={"orphan_justification": "founder-directed exploratory signal"})
    assert missing_experiment_fields(justified) == []


def test_track_c_autonomous_requires_evidence_before_approval():
    exp = _exp(permissions={"track": "C", "autonomous": True})
    assert is_track_c_autonomous(exp)
    assert "track_c_evidence" in missing_experiment_fields(exp)
    evidenced = _exp(permissions={"track": "C", "autonomous": True, "evidence": ["pilot-log"]})
    assert missing_experiment_fields(evidenced) == []


def test_track_b_requires_hypothesis():
    from aios.governance.innovation import track_b_hypothesis_required
    exp = _exp(hypothesis_id=None, permissions={"track": "B", "orphan_justification": "x"})
    ok, reason = track_b_hypothesis_required(exp)
    assert not ok
    assert "hypothesis" in reason.lower()
    assert "track_b_hypothesis_required" in missing_experiment_fields(exp)
    ok2 = _exp(hypothesis_id="h1", permissions={"track": "B"})
    assert track_b_hypothesis_required(ok2)[0] is True
    assert "track_b_hypothesis_required" not in missing_experiment_fields(ok2)


def test_autonomous_action_guard_fail_closed():
    from aios.governance.innovation import autonomous_action_guard
    ok, reason = autonomous_action_guard(track="C", autonomous=True, has_evidence=False, founder_approved=True, action="outreach")
    assert not ok
    assert "evidence" in reason.lower()
    ok, reason = autonomous_action_guard(track="C", autonomous=True, has_evidence=True, founder_approved=False, action="outreach")
    assert not ok
    assert "Founder" in reason
    ok, _ = autonomous_action_guard(track="C", autonomous=True, has_evidence=True, founder_approved=True, action="outreach")
    assert ok
    ok, _ = autonomous_action_guard(track="B", autonomous=True, has_evidence=False, founder_approved=False, action="outreach")
    assert ok  # guard scoped to Track C autonomous only


def test_mvp_type_promotion_guard():
    proto = _exp(mvp_type="experimental_prototype", result="success")
    allowed, reason = production_promotion_allowed(proto)
    assert not allowed
    assert "review" in reason
    mvp = _exp(mvp_type="commercial_mvp", result="failure")
    assert production_promotion_allowed(mvp)[0] is False
    ok = _exp(mvp_type="commercial_mvp", result="success")
    assert production_promotion_allowed(ok)[0] is True


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
