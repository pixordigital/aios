"""Jev controlled evaluation: Noul / Choice / Score decision-aid harness.

Deterministic evaluation over a controlled decision set. Jev never overrides
mandatory eligibility; it may rank among already-eligible candidates.

Boundaries (non-negotiable):
- mandatory eligibility is enforced by Python; Jev cannot override it
- confidence is not evidence; output must carry both separately
- measurable-value gate required before rollout/promotion decisions
- vendor/LGPD assessment required before personal/customer data enters harness
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

JEV_DECISION_TYPES = ("noul", "choice", "score")

Approach = Literal["python_only", "jev", "hybrid"]


@dataclass
class JevAssessment:
    vendor_ok: bool = False
    lgpd_ok: bool = False
    personal_data: bool = False
    notes: str = ""

    @property
    def allowed(self) -> bool:
        # No fake assessment: personal/customer data requires explicit flags.
        if self.personal_data:
            return bool(self.vendor_ok and self.lgpd_ok)
        return True


def assess_data_readiness(case: dict[str, Any]) -> JevAssessment:
    """Vendor/LGPD gate. Required before personal/customer data in harness."""
    data = case.get("data_assessment") or {}
    if not isinstance(data, dict):
        data = {}
    personal = bool(case.get("contains_personal_data") or case.get("contains_customer_data") or data.get("personal_data"))
    return JevAssessment(
        vendor_ok=bool(data.get("vendor_ok", False)),
        lgpd_ok=bool(data.get("lgpd_ok", False)),
        personal_data=personal,
        notes=str(data.get("notes") or ""),
    )


def measurable_value_gate(case: dict[str, Any]) -> tuple[bool, str]:
    """Block rollout decisions without measurable value criteria."""
    gate = case.get("measurable_value") or {}
    if not isinstance(gate, dict):
        gate = {}
    metric = str(gate.get("metric") or "").strip()
    baseline = gate.get("baseline")
    target = gate.get("target")
    if not metric:
        return False, "measurable_value.metric required"
    if baseline is None or target is None:
        return False, "measurable_value.baseline and target required"
    return True, "ok"


def _python_only(case: dict) -> str:
    # Deterministic fallback rule standing in for the Python optimisation.
    return str(case.get("python_outcome") or "noul")


def _jev(case: dict) -> str:
    # Jev may propose ranking only among already-eligible candidates.
    eligible = case.get("eligible_candidates")
    proposed = str(case.get("jev_outcome") or case.get("python_outcome") or "noul")
    if isinstance(eligible, list) and eligible:
        if proposed not in [str(x) for x in eligible] and proposed != "noul":
            return "human_review"
    return proposed


def _hybrid(case: dict) -> str:
    # Hybrid: deterministic floor + structured signal; ties resolved deterministically.
    py = str(case.get("python_outcome") or "")
    jev = str(case.get("jev_outcome") or "")
    if py and jev and jev != py:
        return "human_review"
    return py or "noul"


APPROACHES: tuple[str, ...] = ("python_only", "jev", "hybrid")


def decide(approach: Approach, case: dict, reference: str | None = None) -> dict[str, Any]:
    """Decision result with explicit evidence/confidence separation.

    Jev confidence is a ranking signal only; never evidence of eligibility.
    """
    assessment = assess_data_readiness(case)
    gate_ok, gate_reason = measurable_value_gate(case)
    eligible = case.get("eligible_candidates")
    if isinstance(eligible, list) and eligible:
        # Mandatory eligibility: Python owns it. Jev cannot select outside.
        py = str(case.get("python_outcome") or "noul")
        if py not in [str(x) for x in eligible] and py != "noul":
            py = "human_review"
            case = {**case, "python_outcome": py}
    if not assessment.allowed:
        return {
            "outcome": "blocked_data_assessment",
            "confidence": 0.0,
            "evidence": {"vendor_ok": assessment.vendor_ok, "lgpd_ok": assessment.lgpd_ok, "personal_data": assessment.personal_data},
            "confidence_is_evidence": False,
            "gate_ok": gate_ok,
            "gate_reason": gate_reason,
        }
    outcome = {"python_only": _python_only, "jev": _jev, "hybrid": _hybrid}[approach](case)
    # confidence is advisory metadata, never proof
    confidence = float(case.get("confidence", 0.0) or 0.0)
    confidence = max(0.0, min(1.0, confidence))
    result = {
        "outcome": outcome,
        "confidence": confidence,
        "confidence_is_evidence": False,
        "evidence": {
            "reference_present": reference is not None,
            "python_outcome": case.get("python_outcome"),
            "jev_outcome": case.get("jev_outcome"),
            "eligible_candidates": eligible,
            "assessment": {"vendor_ok": assessment.vendor_ok, "lgpd_ok": assessment.lgpd_ok, "personal_data": assessment.personal_data},
        },
        "gate_ok": gate_ok,
        "gate_reason": gate_reason,
    }
    if not gate_ok:
        result["outcome"] = "blocked_measurable_value_gate"
    return result


def run_controlled_evaluation(
    cases: list[dict],
    *,
    approaches: tuple[str, ...] = APPROACHES,
) -> dict:
    """Return per-approach agreement, consistency and failure counts against the reference."""
    results: dict[str, dict] = {}
    for approach in approaches:
        decisions = [decide(approach, c, c.get("reference")) for c in cases]
        outcomes = [d["outcome"] for d in decisions]
        refs = [c.get("reference") for c in cases]
        agree = sum(1 for o, r in zip(outcomes, refs) if r is not None and o == r)
        failures = sum(1 for d in decisions if str(d["outcome"]).startswith("blocked_"))
        results[approach] = {
            "agreement": round(agree / len(cases), 4) if cases else 0.0,
            "consistent": len(set(outcomes)) <= 1,
            "decisions": len(outcomes),
            "failures": failures,
            "blocked_data_assessment": sum(1 for d in decisions if d["outcome"] == "blocked_data_assessment"),
            "blocked_measurable_value_gate": sum(1 for d in decisions if d["outcome"] == "blocked_measurable_value_gate"),
        }
    return results
