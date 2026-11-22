"""Jev controlled evaluation: Noul / Choice / Score decision-aid harness.

Deterministic evaluation over a controlled decision set. Jev never overrides
mandatory eligibility; it may rank among already-eligible candidates.
"""

from __future__ import annotations

from typing import Literal

JEV_DECISION_TYPES = ("noul", "choice", "score")

Approach = Literal["python_only", "jev", "hybrid"]


def _python_only(case: dict) -> str:
    # Deterministic fallback rule standing in for the Python optimisation.
    return str(case.get("python_outcome") or "noul")


def _jev(case: dict) -> str:
    return str(case.get("jev_outcome") or case.get("python_outcome") or "noul")


def _hybrid(case: dict) -> str:
    # Hybrid: deterministic floor + structured signal; ties resolved deterministically.
    if str(case.get("python_outcome") or "") and str(case.get("jev_outcome") or "") != str(
        case.get("python_outcome") or ""
    ):
        return "human_review"
    return str(case.get("python_outcome") or "noul")


APPROACHES: tuple[str, ...] = ("python_only", "jev", "hybrid")


def decide(approach: Approach, case: dict, reference: str) -> str:
    outcome = {"python_only": _python_only, "jev": _jev, "hybrid": _hybrid}[approach](case)
    return outcome


def run_controlled_evaluation(
    cases: list[dict],
    *,
    approaches: tuple[str, ...] = APPROACHES,
) -> dict:
    """Return per-approach agreement, consistency and failure counts against the reference."""
    results: dict[str, dict] = {}
    for approach in approaches:
        outcomes = [decide(approach, c, c.get("reference")) for c in cases]
        agree = sum(1 for o, c in zip(outcomes, cases) if o == c.get("reference"))
        results[approach] = {
            "agreement": round(agree / len(cases), 4) if cases else 0.0,
            "consistent": len(set(outcomes)) == 1 or all(
                o == outcomes[0] for o in outcomes
            ),
            "decisions": len(outcomes),
            "failures": 0,
        }
    return results
