"""Authoritative KPIs: deterministic Python calculations."""

from aios.governance.kpi import (
    average_deal_size,
    conversion_rate,
    governance_kpis_snapshot,
    interpret_kpis,
    kpi_catalog,
    validate_target_proposal,
    win_rate,
)


def test_win_rate():
    assert win_rate(8, 2) == 0.8
    assert win_rate(0, 0) == 0.0
    assert win_rate(3, 1) == 0.75


def test_conversion_rate():
    assert conversion_rate(5, 20) == 0.25
    assert conversion_rate(0, 0) == 0.0


def test_average_deal_size():
    assert average_deal_size([100.0, 200.0]) == 150.0
    assert average_deal_size([]) == 0.0


def test_interpretation_uses_only_supplied_baseline():
    result = interpret_kpis(
        {"win_rate": 0.2, "conversion_rate": 0.1},
        {"win_rate": 0.25, "conversion_rate": 0.05},
    )
    assert "win_rate: 0.2 (down 0.05 vs baseline)" in result["items"]
    assert any("up" in line for line in result["items"])
    assert result["watch"] == "win_rate"
    assert "Largest relative decline: win_rate" in result["summary"]


def test_interpretation_without_baseline_invents_no_target():
    result = interpret_kpis({"win_rate": 0.8})
    assert result["watch"] is None
    assert "no baseline" in result["summary"]
    assert "target" not in result["summary"]
    assert result["guardrails"]["no_invented_targets"] is True


def test_kpi_catalog_covers_levels_and_marks_uninstrumented():
    catalog = kpi_catalog()
    levels = {m["level"] for m in catalog["metrics"]}
    assert {"business", "department", "process", "agent_team", "infra_resource"} <= levels
    statuses = {m["status"] for m in catalog["metrics"]}
    assert "not_instrumented" in statuses
    unknown = [m for m in catalog["metrics"] if m["status"] == "not_instrumented"]
    assert all(m["source"] == "not_instrumented" for m in unknown)


def test_kpi_catalog_filter_by_category():
    gov = kpi_catalog(category="governance")
    assert gov["count"] > 0
    assert all(m["category"] == "governance" for m in gov["metrics"])


def test_target_proposal_requires_baseline_and_evidence():
    result = validate_target_proposal(
        metric_key="crm.win_rate",
        target_value=0.7,
        baseline_value=None,
        baseline_window_days=30,
        evidence="",
        owner="sales",
        balancing_metrics=[],
    )
    assert result["ok"] is False
    assert "baseline_value required; no target before baseline" in result["errors"]
    assert "evidence required (query, report, incident log, or audit reference)" in result["errors"]
    assert result["persistence"]["persisted"] is False


def test_target_proposal_rejects_uninstrumented_metric():
    result = validate_target_proposal(
        metric_key="department.objective_attainment",
        target_value=0.8,
        baseline_value=0.5,
        baseline_window_days=30,
        evidence="quarterly review",
        owner="ops",
        balancing_metrics=["process.on_time_completion"],
    )
    assert result["ok"] is False
    assert "metric not_instrumented; cannot set target until instrumented" in result["errors"]


def test_governance_snapshot_marks_missing_sources_unknown():
    snap = governance_kpis_snapshot(
        audit_count=3,
        decided_approvals=2,
        rejected_approvals=1,
        approval_latency_hours=1.5,
        open_incidents=None,
        mttr_hours=None,
        open_privacy_requests=None,
        privacy_completion_rate=None,
        sources={"security_incidents": "unavailable"},
    )
    by_key = {m["key"]: m for m in snap["metrics"]}
    assert by_key["governance.audit_events"]["status"] == "available"
    assert by_key["security.incidents_open"]["status"] == "unknown"
    assert by_key["privacy.requests_open"]["status"] == "unknown"
    assert snap["guardrails"]["no_fake_metrics"] is True
