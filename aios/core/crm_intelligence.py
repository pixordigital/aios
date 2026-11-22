"""Revenue & Customer Intelligence: accounts, contacts and unified interaction timeline.

The CRM owns customer state; the knowledge system owns searchable history.
Do not put customer history into `CrmDeal.extra_data`.
"""

from datetime import datetime, timedelta, timezone

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


class Account(Base, TimestampMixin):
    """Company/customer entity. CNPJ identifies Brazilian companies when known."""

    __tablename__ = "crm_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    cnpj: Mapped[str | None] = mapped_column(String(18), nullable=True, index=True)
    industry: Mapped[str] = mapped_column(String(120), default="")
    website: Mapped[str] = mapped_column(String(500), default="")
    size: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(30), default="prospect")
    owner_agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    health_score: Mapped[float] = mapped_column(default=0.5)  # 0..1
    lifetime_value: Mapped[float] = mapped_column(default=0.0)
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("org_id", "cnpj", name="uq_crm_account_org_cnpj"),)


class Contact(Base, TimestampMixin):
    """Decision-maker. One contact may relate to several accounts."""

    __tablename__ = "crm_contacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("crm_accounts.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    role: Mapped[str] = mapped_column(String(160), default="")
    source: Mapped[str] = mapped_column(String(120), default="")
    is_decision_maker: Mapped[bool] = mapped_column(default=False)
    email_verified: Mapped[bool] = mapped_column(default=False)
    contact_allowed: Mapped[bool] = mapped_column(default=True)
    lawful_basis: Mapped[str] = mapped_column(String(40), default="")
    opt_out_at: Mapped[datetime | None] = mapped_column(nullable=True)
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("org_id", "email", name="uq_crm_contact_org_email"),)


class InteractionEvent(Base, TimestampMixin):
    """Append-only unified timeline across channels and entities."""

    __tablename__ = "crm_interactions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("crm_accounts.id"), nullable=True, index=True)
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("crm_contacts.id"), nullable=True, index=True)
    deal_id: Mapped[str | None] = mapped_column(ForeignKey("crm_deals.id"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(40), default="manual")
    direction: Mapped[str] = mapped_column(String(20), default="outbound")
    event_type: Mapped[str] = mapped_column(String(60), default="message")
    summary: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[datetime] = mapped_column(default=_now, index=True)
    source: Mapped[str] = mapped_column(String(120), default="")
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)


# --- Deterministic intelligence ----------------------------------------------


def relationship_health(
    *,
    days_since_last_contact: int | None,
    open_commitments: int,
    overdue_commitments: int,
    support_tickets_open: int,
    renewed: bool = False,
) -> tuple[float, str]:
    """Deterministic 0..1 health plus a reason. No LLM authority."""
    score = 0.6
    reasons = []
    if days_since_last_contact is None:
        score -= 0.2
        reasons.append("no contact recorded")
    elif days_since_last_contact > 45:
        score -= 0.3
        reasons.append("stale relationship")
    elif days_since_last_contact > 21:
        score -= 0.1
        reasons.append("contact ageing")
    score -= min(0.3, overdue_commitments * 0.1)
    if overdue_commitments:
        reasons.append(f"{overdue_commitments} overdue commitment(s)")
    score -= min(0.2, support_tickets_open * 0.05)
    if support_tickets_open:
        reasons.append(f"{support_tickets_open} open ticket(s)")
    if open_commitments == 0 and days_since_last_contact is not None and days_since_last_contact <= 21:
        score += 0.1
        reasons.append("recent contact, no open commitments")
    if renewed:
        score += 0.15
        reasons.append("renewed")
    score = max(0.0, min(1.0, round(score, 3)))
    return score, "; ".join(reasons) or "baseline"


def sales_priority(
    *, icp_fit: float, recency_days: int, attempts: int, deal_value: float, stage_weight: float
) -> float:
    """Deterministic prioritisation heuristic. A predictive model needs evidence first."""
    recency = max(0.0, 1.0 - recency_days / 30.0)
    return round(
        icp_fit * 0.35
        + recency * 0.25
        + min(attempts, 5) * 0.04
        + min(deal_value / 100_000.0, 1.0) * 0.2
        + stage_weight * 0.16,
        4,
    )


def retention_cutoff(now: datetime, retention_days: int) -> datetime:
    return now - timedelta(days=max(0, retention_days))
