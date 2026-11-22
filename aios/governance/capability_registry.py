"""Capability registry and Solution-Fit engine.

A high opportunity score never compensates for an infeasible solution, weak
evidence or a prohibited contact. Dispositions are deterministic.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
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


MATURITY_LEVELS = ("concept", "prototype", "pilot", "production", "deprecated")

# A capability can only serve a live opportunity at these levels.
SELLABLE_MATURITY = ("pilot", "production")

DISPOSITIONS = (
    "qualified",
    "research_required",
    "nurture",
    "future_opportunity",
    "disqualified",
    "restricted",
)


class Capability(Base, TimestampMixin):
    """Actual maturity, limits and evidence — not the marketing claim."""

    __tablename__ = "capabilities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    capability_key: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(255))
    maturity: Mapped[str] = mapped_column(String(20), default="concept", index=True)
    supported_use_cases: Mapped[list] = mapped_column(JSON, default=list)
    integrations: Mapped[list] = mapped_column(JSON, default=list)
    complexity: Mapped[str] = mapped_column(String(20), default="medium")  # low|medium|high
    limitations: Mapped[list] = mapped_column(JSON, default=list)
    dependencies: Mapped[list] = mapped_column(JSON, default=list)
    pricing_notes: Mapped[str] = mapped_column(Text, default="")
    deployment_evidence: Mapped[list] = mapped_column(JSON, default=list)
    is_commercially_available: Mapped[bool] = mapped_column(default=False)
    __table_args__ = (UniqueConstraint("org_id", "capability_key", name="uq_capability_org_key"),)


class SolutionFitAssessment(Base, TimestampMixin):
    """Per-opportunity fit, kept as separate dimensions plus evidence confidence."""

    __tablename__ = "solution_fit_assessments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    subject_type: Mapped[str] = mapped_column(String(20), default="company")
    subject_id: Mapped[str] = mapped_column(String(36), index=True)
    capability_id: Mapped[str | None] = mapped_column(ForeignKey("capabilities.id"), nullable=True)
    problem_fit: Mapped[float] = mapped_column(default=0.0)  # 0..1
    capability_fit: Mapped[float] = mapped_column(default=0.0)
    feasibility: Mapped[float] = mapped_column(default=0.0)
    commercial_viability: Mapped[float] = mapped_column(default=0.0)
    buying_readiness: Mapped[float] = mapped_column(default=0.0)
    evidence_confidence: Mapped[float] = mapped_column(default=0.0)
    contact_allowed: Mapped[bool] = mapped_column(default=True)
    disposition: Mapped[str] = mapped_column(String(30), default="research_required", index=True)
    rationale: Mapped[str] = mapped_column(Text, default="")


# --- Deterministic scoring ----------------------------------------------------


def solution_fit(
    capability: Capability | None,
    *,
    problem_fit: float,
    feasibility: float,
    commercial_viability: float,
    buying_readiness: float,
    evidence_confidence: float,
    contact_allowed: bool = True,
) -> tuple[str, str]:
    """Return (disposition, rationale). Capability fit comes from the registry."""
    if not contact_allowed:
        return "restricted", "contact channel prohibited or opted out"
    if capability is None:
        return "research_required", "no capability recorded for this problem"
    if capability.maturity not in SELLABLE_MATURITY or not capability.is_commercially_available:
        return "future_opportunity", f"capability maturity is {capability.maturity}"
    if evidence_confidence < 0.4:
        return "research_required", "evidence confidence too low"
    if feasibility < 0.4:
        return "disqualified", "infeasible with current capabilities"
    if problem_fit < 0.4:
        return "disqualified", "weak problem fit"
    if buying_readiness < 0.4:
        return "nurture", "not a suitable time to buy"
    if commercial_viability < 0.4:
        return "nurture", "commercial viability unproven"
    if min(problem_fit, feasibility, commercial_viability, buying_readiness, evidence_confidence) < 0.6:
        return "research_required", "one or more dimensions below qualification bar"
    return "qualified", "all dimensions above qualification bar"


def capability_fit_score(capability: Capability, required_use_case: str | None) -> float:
    """Deterministic 0..1 signal from declared support and evidence."""
    if required_use_case and required_use_case not in (capability.supported_use_cases or []):
        return 0.0
    base = {"concept": 0.2, "prototype": 0.45, "pilot": 0.7, "production": 0.9, "deprecated": 0.0}.get(
        capability.maturity, 0.0
    )
    if capability.deployment_evidence:
        base = min(1.0, base + 0.1)
    return base


WORKFLOW_STAGES = (
    "company_discovery",
    "prospect_intelligence",
    "solution_fit",
    "qualification",
    "outreach",
    "meeting_booking",
    "sales_handoff",
    "outcome_feedback",
)


def next_stage(current: str) -> str | None:
    try:
        idx = WORKFLOW_STAGES.index(current)
    except ValueError:
        return None
    return WORKFLOW_STAGES[idx + 1] if idx + 1 < len(WORKFLOW_STAGES) else None
