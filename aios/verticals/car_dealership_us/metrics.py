"""Business-outcome arithmetic for US car dealership vertical.

Owner question: value vs cost. Rates from counted rows only; attribution
reported with source/confidence, never as assumed revenue truth.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutcomeCounts:
    enquiries: int = 0
    answered: int = 0
    qualified_leads: int = 0
    follow_ups_attempted: int = 0
    follow_ups_completed: int = 0
    deals_attributed: int = 0
    attributed_value: float = 0.0  # primary (currency set by caller/reporting); legacy alias kept in output
    human_handoffs: int = 0
    failed: int = 0


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def summarize_outcomes(
    counts: OutcomeCounts,
    *,
    attribution_source: str,
    attribution_confidence: str = "medium",
    currency: str = "USD",
) -> dict:
    val = round(counts.attributed_value, 2)
    return {
        "enquiries": counts.enquiries,
        "answered": counts.answered,
        "unanswered": max(counts.enquiries - counts.answered, 0),
        "answered_pct": _pct(counts.answered, counts.enquiries),
        "qualified_leads": counts.qualified_leads,
        "qualification_pct": _pct(counts.qualified_leads, counts.answered),
        "follow_ups_attempted": counts.follow_ups_attempted,
        "follow_ups_completed": counts.follow_ups_completed,
        "follow_up_completion_pct": _pct(
            counts.follow_ups_completed, counts.follow_ups_attempted
        ),
        "human_handoffs": counts.human_handoffs,
        "human_handoff_pct": _pct(counts.human_handoffs, counts.enquiries),
        "failed": counts.failed,
        "failure_pct": _pct(counts.failed, counts.enquiries),
        "deals_attributed": counts.deals_attributed,
        "attributed_value": val,
        "attributed_value_brl": val,
        "currency": currency,
        "attribution_source": attribution_source,
        "attribution_confidence": attribution_confidence,
    }
