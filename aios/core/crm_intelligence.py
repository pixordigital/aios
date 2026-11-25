"""Revenue & Customer Intelligence: accounts, contacts and unified interaction timeline.

The CRM owns customer state; the knowledge system owns searchable history.
Do not put customer history into `CrmDeal.extra_data`.

extra_data is legacy/tactical only. Known keys are accessed via DEAL_EXTRA_KEYS
adapter; new ad-hoc keys must not be added.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint, select
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


# --- extra_data adapter (legacy/tactical only) -------------------------------

DEAL_EXTRA_KEYS = {
    "notes": "Operator notes. Legacy: stored in extra_data; prefer typed timeline when possible.",
    "last_summary": "Last SDR/agent summary. Legacy mirror for fast reads.",
    "last_contacted_at": "ISO timestamp of last contact. Legacy mirror.",
    "next_follow_up": "ISO timestamp for next follow-up. Legacy operational field.",
    "follow_up_note": "Follow-up note. Legacy operational field.",
    "sdr_history": "Bounded SDR exchange history. Legacy mirror; InteractionEvent is canonical timeline.",
    "sdr_touched": "Bool flag set by SDR handoff.",
    "last_ai_notes": "Legacy AI note field from CRM tools.",
    "attempts": "Contact attempts counter used by timing heuristic.",
    "company": "Legacy company field; Account is canonical when linked.",
    "custom_fields": "Pipeline custom fields live under org extra_data definitions; deal values may be mirrored.",
}

# Keys known to be safe legacy mirrors/adapters. Anything else is ad-hoc.
_KNOWN_EXTRA_KEYS = set(DEAL_EXTRA_KEYS) | {
    "source",
    "lead_status",
    "batch",
    "icp",
    "website",
    "industry",
    "location",
    "company_size",
    "source_url",
    "qualification_reason",
    "pain_points",
    "decision_maker",
}


def deal_extra_get(deal, key: str, default=None):
    extra = deal.extra_data if isinstance(getattr(deal, "extra_data", None), dict) else {}
    return extra.get(key, default)


def deal_extra_set(deal, key: str, value) -> None:
    """Set a known legacy extra_data key. New unknown keys are blocked."""
    if key not in _KNOWN_EXTRA_KEYS:
        raise ValueError(f"ad-hoc CrmDeal.extra_data key blocked: {key}")
    extra = dict(deal.extra_data or {})
    if value in (None, "", [], {}):
        extra.pop(key, None)
    else:
        extra[key] = value
    deal.extra_data = extra


def deal_entity_kind(deal) -> str:
    """Derived, no schema change. Deal mixes lead/opportunity in current model."""
    stage = getattr(deal, "stage", "") or ""
    if stage in {"closed_won", "closed_lost"}:
        return "closed_deal"
    if stage in {"opportunity", "sql"}:
        return "opportunity"
    return "lead"


async def find_account_for_deal(db, deal):
    row, _meta = await find_account_for_deal_with_meta(db, deal)
    return row


async def find_account_for_deal_with_meta(db, deal):
    """Prefer typed FK; legacy extra_data/identifier heuristics only for unlinked rows."""
    account_id = getattr(deal, "account_id", None)
    if account_id:
        row = await db.get(Account, str(account_id))
        if row is None or row.org_id != deal.org_id:
            return None, {"kind": "none", "source": "typed_fk_invalid", "validated": False, "authoritative": False}
        return row, {"kind": "typed_fk", "source": "crm_deals.account_id", "validated": True, "authoritative": True}
    extra = deal.extra_data if isinstance(getattr(deal, "extra_data", None), dict) else {}
    account_id = extra.get("account_id")
    if account_id:
        row = await db.get(Account, str(account_id))
        if row and row.org_id == deal.org_id:
            return row, {"kind": "heuristic", "source": "extra_data.account_id", "validated": False, "authoritative": False}
    cnpj = str(extra.get("cnpj") or "").strip()
    if cnpj:
        row = (await db.execute(select(Account).where(Account.org_id == deal.org_id, Account.cnpj == cnpj))).scalar_one_or_none()
        if row:
            return row, {"kind": "heuristic", "source": "cnpj_exact", "validated": False, "authoritative": False}
    name = str(getattr(deal, "lead_name", "") or "").strip()
    if name:
        row = (await db.execute(select(Account).where(Account.org_id == deal.org_id, Account.name == name).limit(1))).scalar_one_or_none()
        if row:
            return row, {"kind": "heuristic", "source": "lead_name_exact", "validated": False, "authoritative": False}
    return None, {"kind": "none", "source": "unlinked", "validated": False, "authoritative": False}


async def find_contact_for_deal(db, deal):
    row, _meta = await find_contact_for_deal_with_meta(db, deal)
    return row


async def find_contact_for_deal_with_meta(db, deal):
    """Prefer typed FK; legacy extra_data/identifier heuristics only for unlinked rows."""
    contact_id = getattr(deal, "contact_id", None)
    if contact_id:
        row = await db.get(Contact, str(contact_id))
        if row is None or row.org_id != deal.org_id:
            return None, {"kind": "none", "source": "typed_fk_invalid", "validated": False, "authoritative": False}
        return row, {"kind": "typed_fk", "source": "crm_deals.contact_id", "validated": True, "authoritative": True}
    extra = deal.extra_data if isinstance(getattr(deal, "extra_data", None), dict) else {}
    contact_id = extra.get("contact_id")
    if contact_id:
        row = await db.get(Contact, str(contact_id))
        if row and row.org_id == deal.org_id:
            return row, {"kind": "heuristic", "source": "extra_data.contact_id", "validated": False, "authoritative": False}
    email = str(getattr(deal, "lead_email", "") or "").strip().lower()
    if email:
        row = (await db.execute(select(Contact).where(Contact.org_id == deal.org_id, Contact.email == email))).scalar_one_or_none()
        if row:
            return row, {"kind": "heuristic", "source": "lead_email_exact", "validated": False, "authoritative": False}
    phone = "".join(ch for ch in str(getattr(deal, "lead_phone", "") or "") if ch.isdigit())
    if phone:
        rows = (await db.execute(select(Contact).where(Contact.org_id == deal.org_id))).scalars().all()
        for row in rows:
            if "".join(ch for ch in str(row.phone or "") if ch.isdigit()) == phone:
                return row, {"kind": "heuristic", "source": "lead_phone_digits", "validated": False, "authoritative": False}
    return None, {"kind": "none", "source": "unlinked", "validated": False, "authoritative": False}


def deal_360_payload(deal, account=None, contact=None, *, account_link=None, contact_link=None) -> dict:
    extra = deal.extra_data if isinstance(getattr(deal, "extra_data", None), dict) else {}
    account_link = account_link or {"kind": "none", "source": "unlinked", "validated": False, "authoritative": False}
    contact_link = contact_link or {"kind": "none", "source": "unlinked", "validated": False, "authoritative": False}
    return {
        "id": deal.id,
        "entity_kind": deal_entity_kind(deal),
        "entity_kind_note": "Derived heuristic; CrmDeal schema currently mixes lead/opportunity.",
        "lead_name": deal.lead_name,
        "lead_email": deal.lead_email,
        "lead_phone": deal.lead_phone,
        "stage": deal.stage,
        "value": deal.value,
        "currency": getattr(deal, "currency", "BRL"),
        "score": deal.score,
        "source": deal.source,
        "agent_id": deal.agent_id,
        "team_id": deal.team_id,
        "pipeline": deal.pipeline,
        "close_date": deal.close_date.isoformat() if getattr(deal, "close_date", None) else None,
        "probability": getattr(deal, "probability", 0.0),
        "account": {"id": account.id, "name": account.name, "cnpj": account.cnpj} if account else None,
        "account_link": {
            **account_link,
            "note": "Typed nullable FK preferred; legacy extra_data/identifier heuristic only for unlinked rows.",
        },
        "contact": {"id": contact.id, "name": contact.name, "email": contact.email, "phone": contact.phone} if contact else None,
        "contact_link": {
            **contact_link,
            "note": "Typed nullable FK preferred; legacy extra_data/identifier heuristic only for unlinked rows.",
        },
        "legacy_extra_keys": sorted(extra.keys()),
        "legacy_extra_data_note": "extra_data is legacy/tactical; use typed CRM objects/timeline where available.",
    }


async def record_interaction_event(
    db, *, org_id: str, deal_id: str | None = None, account_id: str | None = None,
    contact_id: str | None = None, channel: str = "manual", direction: str = "outbound",
    event_type: str = "message", summary: str = "", occurred_at: datetime | None = None,
    source: str = "crm2", provenance: dict | None = None,
) -> InteractionEvent:
    ev = InteractionEvent(
        org_id=org_id,
        deal_id=deal_id,
        account_id=account_id,
        contact_id=contact_id,
        channel=(channel or "manual")[:40],
        direction=(direction or "outbound")[:20],
        event_type=(event_type or "message")[:60],
        summary=(summary or "")[:4000],
        occurred_at=occurred_at or _now(),
        source=(source or "crm2")[:120],
        provenance=provenance or {},
    )
    db.add(ev)
    await db.flush()
    return ev
