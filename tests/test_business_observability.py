from aios.core.business_observability import (
    BusinessObservability,
    EvalCase,
    EvalResult,
    SLO,
)


def test_record_and_summary():
    obs = BusinessObservability()
    obs.record_metric("revenue_mrr", 12000.0)
    obs.record_metric("churn_rate", 0.02)

    summary = obs.summary()
    assert summary["metrics"] == {"revenue_mrr": 12000.0, "churn_rate": 0.02}
    assert summary["total"] == 0
    assert summary["passed"] == 0
    assert summary["failed"] == 0
    assert summary["all_passed"] is False
    assert summary["results"] == []


def test_missing_metric_fails_eval_no_fabricated_pass():
    obs = BusinessObservability()
    case = EvalCase(name="mrr-target", metric="revenue_mrr", target=10000.0, comparator="gte")

    result = obs.evaluate_case(case)

    assert isinstance(result, EvalResult)
    assert result.passed is False
    assert result.actual is None
    assert result.metric == "revenue_mrr"
    assert "missing metric" in result.reason
    assert obs.summary()["failed"] == 1
    assert obs.summary()["passed"] == 0


def test_eval_case_pass_and_fail():
    obs = BusinessObservability()
    obs.record_metric("revenue_mrr", 12000.0)
    obs.record_metric("churn_rate", 0.05)

    pass_case = EvalCase(name="mrr-ok", metric="revenue_mrr", target=10000.0, comparator="gte")
    fail_case = EvalCase(name="churn-ok", metric="churn_rate", target=0.03, comparator="lte")

    pass_result = obs.evaluate_case(pass_case)
    fail_result = obs.evaluate_case(fail_case)

    assert pass_result.passed is True
    assert pass_result.actual == 12000.0
    assert pass_result.reason == "ok"

    assert fail_result.passed is False
    assert fail_result.actual == 0.05
    assert "failed" in fail_result.reason

    summary = obs.summary()
    assert summary["total"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["all_passed"] is False


def test_slo_check():
    slo = SLO(name="mrr", metric="revenue_mrr", target=10000.0, comparator="gte")
    assert slo.check(12000.0) is True
    assert slo.check(8000.0) is False
