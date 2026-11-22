"""Model Intelligence: registry, eligibility filters and cost-per-success optimisation.

Python owns pricing math, eligibility, optimisation, deployment and rollback.
Jev or any LLM may only add a bounded ranking signal among already-eligible
candidates; it can never override mandatory constraints or approval gates.
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


MODEL_TIERS = (0, 1, 2, 3)


class ModelRegistryEntry(Base, TimestampMixin):
    """One provider/model configuration. Prices are versioned per entry."""

    __tablename__ = "model_registry"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    model_key: Mapped[str] = mapped_column(String(160))
    provider: Mapped[str] = mapped_column(String(80))
    tier: Mapped[int] = mapped_column(default=1)
    input_price_per_1m: Mapped[float] = mapped_column(default=0.0)
    output_price_per_1m: Mapped[float] = mapped_column(default=0.0)
    price_currency: Mapped[str] = mapped_column(String(8), default="USD")
    quality_score: Mapped[float] = mapped_column(default=0.0)  # 0..1 from evals
    reliability: Mapped[float] = mapped_column(default=1.0)  # success rate 0..1
    latency_p95_ms: Mapped[int] = mapped_column(default=0)
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    context_window: Mapped[int] = mapped_column(default=0)
    privacy_ok: Mapped[bool] = mapped_column(default=True)
    contract_ok: Mapped[bool] = mapped_column(default=True)
    approved: Mapped[bool] = mapped_column(default=False)
    config_version: Mapped[str] = mapped_column(String(40), default="1")
    notes: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (
        UniqueConstraint("org_id", "model_key", name="uq_model_registry_org_key"),
    )


# --- Deterministic optimisation ----------------------------------------------


def cost_per_successful_task(
    entry: ModelRegistryEntry,
    *,
    avg_input_tokens: float,
    avg_output_tokens: float,
    success_rate: float | None = None,
) -> float:
    """Effective unit economics. Unknown success rate uses the measured reliability."""
    rate = entry.reliability if success_rate is None else success_rate
    if rate <= 0:
        return float("inf")
    per_task = (
        avg_input_tokens * entry.input_price_per_1m
        + avg_output_tokens * entry.output_price_per_1m
    ) / 1_000_000
    return per_task / rate


def eligible_models(
    entries: list[ModelRegistryEntry],
    *,
    min_quality: float = 0.0,
    min_reliability: float = 0.0,
    required_capabilities: tuple[str, ...] = (),
    max_latency_p95_ms: int | None = None,
    privacy_required: bool = True,
    contract_required: bool = True,
    tier: int | None = None,
    min_context_window: int = 0,
    currency: str = "USD",
) -> list[ModelRegistryEntry]:
    """Fail-closed filter. Any unmet mandatory constraint removes the candidate."""
    out = []
    for e in entries:
        if not e.approved:
            continue
        if e.price_currency != currency:
            continue
        if e.quality_score < min_quality or e.reliability < min_reliability:
            continue
        if privacy_required and not e.privacy_ok:
            continue
        if contract_required and not e.contract_ok:
            continue
        if e.context_window < min_context_window:
            continue
        if max_latency_p95_ms is not None and e.latency_p95_ms > max_latency_p95_ms:
            continue
        if tier is not None and e.tier != tier:
            continue
        if not set(required_capabilities).issubset(set(e.capabilities or [])):
            continue
        out.append(e)
    return out


def select_model(
    entries: list[ModelRegistryEntry],
    *,
    avg_input_tokens: float,
    avg_output_tokens: float,
    **filters,
) -> tuple[ModelRegistryEntry | None, float]:
    """Least expensive eligible model by cost per successful task."""
    candidates = eligible_models(entries, **filters)
    if not candidates:
        return None, float("inf")
    scored = [
        (cost_per_successful_task(
            e, avg_input_tokens=avg_input_tokens, avg_output_tokens=avg_output_tokens
        ), e)
        for e in candidates
    ]
    scored.sort(key=lambda pair: (pair[0], -pair[1].quality_score, pair[1].id))
    return scored[0][1], scored[0][0]


def recommend_change(
    current: ModelRegistryEntry,
    proposed: ModelRegistryEntry,
    *,
    avg_input_tokens: float,
    avg_output_tokens: float,
    monthly_tasks: int,
    required_quality: float = 0.0,
) -> dict:
    """Evidence-backed proposal; assumptions labelled, never guaranteed."""
    if not proposed.approved:
        return {"recommended": False, "reason": "proposed model is not approved"}
    if proposed.quality_score < required_quality:
        return {"recommended": False, "reason": "proposed model below required quality"}
    cur = cost_per_successful_task(
        current, avg_input_tokens=avg_input_tokens, avg_output_tokens=avg_output_tokens
    )
    new = cost_per_successful_task(
        proposed, avg_input_tokens=avg_input_tokens, avg_output_tokens=avg_output_tokens
    )
    if new >= cur:
        return {
            "recommended": False,
            "reason": "no cost-per-success improvement",
            "current_cost_per_success": cur,
            "proposed_cost_per_success": new,
        }
    savings = (cur - new) * monthly_tasks
    return {
        "recommended": True,
        "current_model": current.model_key,
        "proposed_model": proposed.model_key,
        "current_cost_per_success": round(cur, 6),
        "proposed_cost_per_success": round(new, 6),
        "expected_monthly_savings": round(savings, 2),
        "quality_delta": round(proposed.quality_score - current.quality_score, 4),
        "latency_delta_ms": proposed.latency_p95_ms - current.latency_p95_ms,
        "monthly_tasks_assumption": monthly_tasks,
        "uncertainty": "savings depend on observed token mix and success rates",
        "requires_founder_approval": True,
    }


def rollback_target(entries: list[ModelRegistryEntry], *, agent_default_key: str, previous_key: str) -> str:
    """Rollback is only to a previously approved configuration."""
    by_key = {e.model_key: e for e in entries if e.approved}
    if previous_key not in by_key:
        return agent_default_key
    return previous_key
