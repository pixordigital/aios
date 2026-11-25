"""Minimal business SLO/eval scaffold.

Tracks business metrics, evaluates cases against recorded values, reports summary.
Missing metrics fail evaluation - no fabricated pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SLO:
    """Service/business level objective for a named metric."""

    name: str
    metric: str
    target: float
    comparator: str = "gte"  # gte | lte | eq

    def check(self, actual: float) -> bool:
        if self.comparator == "gte":
            return actual >= self.target
        if self.comparator == "lte":
            return actual <= self.target
        if self.comparator == "eq":
            return actual == self.target
        raise ValueError(f"unknown comparator: {self.comparator}")


@dataclass
class EvalCase:
    """Single evaluation case against a metric."""

    name: str
    metric: str
    target: float
    comparator: str = "gte"
    description: str = ""


@dataclass
class EvalResult:
    """Outcome of evaluating a case. Never fabricated as pass."""

    case: str
    metric: str
    passed: bool
    actual: float | None
    target: float
    comparator: str
    reason: str


@dataclass
class BusinessObservability:
    """Record business metrics and evaluate SLO cases."""

    metrics: dict[str, float] = field(default_factory=dict)
    results: list[EvalResult] = field(default_factory=list)

    def record_metric(self, name: str, value: float) -> float:
        """Record/update a metric value."""
        value = float(value)
        self.metrics[name] = value
        return value

    def evaluate_case(self, case: EvalCase) -> EvalResult:
        """Evaluate a case against recorded metrics.

        Fails when metric is missing; never fabricates a pass.
        """
        actual = self.metrics.get(case.metric)
        if actual is None:
            result = EvalResult(
                case=case.name,
                metric=case.metric,
                passed=False,
                actual=None,
                target=case.target,
                comparator=case.comparator,
                reason=f"missing metric: {case.metric}",
            )
            self.results.append(result)
            return result

        slo = SLO(
            name=case.name,
            metric=case.metric,
            target=case.target,
            comparator=case.comparator,
        )
        passed = slo.check(actual)
        result = EvalResult(
            case=case.name,
            metric=case.metric,
            passed=passed,
            actual=actual,
            target=case.target,
            comparator=case.comparator,
            reason="ok" if passed else f"{actual} {case.comparator} {case.target} failed",
        )
        self.results.append(result)
        return result

    def summary(self) -> dict[str, Any]:
        """Summarize recorded metrics and evaluation outcomes."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        return {
            "metrics": dict(self.metrics),
            "total": total,
            "passed": passed,
            "failed": failed,
            "all_passed": total > 0 and failed == 0,
            "results": [
                {
                    "case": r.case,
                    "metric": r.metric,
                    "passed": r.passed,
                    "actual": r.actual,
                    "target": r.target,
                    "comparator": r.comparator,
                    "reason": r.reason,
                }
                for r in self.results
            ],
        }
