"""Innovation & Learning: hypotheses, experiments and innovation accounting.

Discipline, not thrift: every experiment declares its riskiest assumption, its
threshold and its stop conditions before it runs. Python decides pass/fail.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from aios.db.engine import Base


def _uuid() -> str:
    import uuid

    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


HYPOTHESIS_KINDS = ("value", "growth", "economic")
HYPOTHESIS_STATUSES = ("draft", "testing", "validated", "invalidated", "paused")
MVP_TYPES = ("architectural_foundation", "commercial_mvp", "experimental_prototype")
EXPERIMENT_RESULTS = ("pending", "success", "failure", "inconclusive", "stopped")
DECISIONS = ("persevere", "pivot", "stop", "iterate")

EXPERIMENT_REQUIRED_FIELDS = (
    "hypothesis_id",
    "riskiest_assumption",
    "metric_name",
    "baseline",
    "sample_size",
    "success_threshold",
    "cost_cap_brl",
    "time_cap_days",
    "owner_id",
    "stop_conditions",
)


class Hypothesis(Base, TimestampMixin):
    __tablename__ = "hypotheses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(20), default="value")
    statement: Mapped[str] = mapped_column(Text, default="")
    riskiest_assumption: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    evidence_summary: Mapped[str] = mapped_column(Text, default="")


class Experiment(Base, TimestampMixin):
    __tablename__ = "experiments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    hypothesis_id: Mapped[str | None] = mapped_column(ForeignKey("hypotheses.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    mvp_type: Mapped[str] = mapped_column(String(30), default="experimental_prototype")
    riskiest_assumption: Mapped[str] = mapped_column(Text, default="")
    metric_name: Mapped[str] = mapped_column(String(120), default="")
    baseline: Mapped[float | None] = mapped_column(nullable=True)
    observed: Mapped[float | None] = mapped_column(nullable=True)
    sample_size: Mapped[int] = mapped_column(default=0)
    success_threshold: Mapped[float | None] = mapped_column(nullable=True)
    direction: Mapped[str] = mapped_column(String(10), default="increase")  # increase|decrease
    cost_cap_brl: Mapped[float] = mapped_column(default=0.0)
    spent_brl: Mapped[float] = mapped_column(default=0.0)
    time_cap_days: Mapped[int] = mapped_column(default=0)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    stop_conditions: Mapped[str] = mapped_column(Text, default="")
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)
    privacy_reviewed: Mapped[bool] = mapped_column(default=False)
    result: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    interpretation: Mapped[str] = mapped_column(Text, default="")
    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)


# --- Deterministic rules ------------------------------------------------------


def missing_experiment_fields(exp: Experiment) -> list[str]:
    missing = []
    for field in EXPERIMENT_REQUIRED_FIELDS:
        value = getattr(exp, field, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def over_budget(exp: Experiment) -> bool:
    return exp.cost_cap_brl > 0 and (exp.spent_brl or 0) > exp.cost_cap_brl


def evaluate_experiment(exp: Experiment) -> str:
    """Pass/fail from the declared threshold. Stops on budget breach."""
    if over_budget(exp):
        return "stopped"
    if exp.observed is None or exp.success_threshold is None:
        return "pending"
    if exp.direction == "decrease":
        passed = exp.observed <= exp.success_threshold
    else:
        passed = exp.observed >= exp.success_threshold
    return "success" if passed else "failure"


def decide_from_result(result: str) -> str:
    return {
        "success": "persevere",
        "failure": "pivot",
        "stopped": "stop",
        "inconclusive": "iterate",
    }.get(result, "iterate")


def innovation_scoreboard(experiments: list[Experiment]) -> dict:
    """Evidence of learning, not feature counts."""
    finished = [e for e in experiments if e.result in {"success", "failure", "inconclusive", "stopped"}]
    validated = [e for e in finished if e.result == "success"]
    cycles = [
        (e.ended_at - e.started_at).days
        for e in finished
        if e.started_at and e.ended_at
    ]
    spend = sum(e.spent_brl for e in experiments)
    return {
        "experiments": len(experiments),
        "finished": len(finished),
        "validated": len(validated),
        "validation_rate": round(len(validated) / len(finished), 3) if finished else None,
        "mean_cycle_days": round(sum(cycles) / len(cycles), 1) if cycles else None,
        "total_spend_brl": round(spend, 2),
        "cost_per_validated_brl": round(spend / len(validated), 2) if validated else None,
    }
