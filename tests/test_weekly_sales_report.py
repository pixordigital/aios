from datetime import date

from aios.core.weekly_sales_report import _recommendations, completed_week, render_pdf


def test_completed_week_uses_previous_monday_to_monday_window():
    start, end = completed_week(date(2026, 11, 18))  # Wednesday
    assert start.date() == date(2026, 11, 9)
    assert end.date() == date(2026, 11, 16)
    assert (end - start).days == 7


def test_recommendations_require_recorded_goal_or_missing_owner_evidence():
    suggestions = _recommendations({"goal": {"target_brl": 1000, "won_brl": 200, "pct": 20},
                                    "unattributed_count": 2})
    assert len(suggestions) == 2
    assert all(item["evidence"] and item["action"] and item["target_url"].startswith("/dashboard/")
               for item in suggestions)
    assert _recommendations({"goal": {"target_brl": 0}, "unattributed_count": 0}) == []


def test_pdf_renders_report_and_aios_links():
    pdf = render_pdf({"week_start": "2026-11-09", "week_end": "2026-11-15", "current": {},
                      "previous": {}, "goal": {}, "agents": [], "stage_changes": [],
                      "unattributed_count": 0}, [], "https://aios.example/dashboard/sales-reports/abc")
    assert pdf.startswith(b"%PDF-")
