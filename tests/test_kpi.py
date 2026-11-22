"""Authoritative KPIs: deterministic Python calculations."""

from aios.governance.kpi import (
    average_deal_size,
    conversion_rate,
    interpret_kpis,
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
