"""LIA — lead acquisition: sources, signals, campaigns and contact eligibility.

AIOS owns the workflow and data model; it still depends on external sources for
business information. Public personal data stays subject to LGPD, and legitimate
interest is not blanket permission. Contact checks are deterministic.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aios.db.engine import Base
from aios.governance.capability_registry import WORKFLOW_STAGES


def _uuid() -> str:
    import uuid

    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


CHANNELS = ("email", "whatsapp_business", "linkedin_human", "inbound_form")
# P0 first. WhatsApp only for eligible, authorised conversations.
CHANNEL_PRIORITY = {"inbound_form": 0, "email": 0, "whatsapp_business": 1, "linkedin_human": 2}

SOURCE_TYPES = (
    "receita_cnpj",
    "company_website",
    "search_api",
    "industry_directory",
    "news",
    "first_party_form",
    "referral",
    "public_tender",
)

DISPOSITIONS = (
    "qualified",
    "research_required",
    "nurture",
    "future_opportunity",
    "disqualified",
    "restricted",
)


class LeadSource(Base, TimestampMixin):
    __tablename__ = "lead_sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(40))
    url: Mapped[str] = mapped_column(String(500), default="")
    terms_notes: Mapped[str] = mapped_column(Text, default="")
    allowed_for_outreach: Mapped[bool] = mapped_column(default=False)


class LeadSignal(Base, TimestampMixin):
    __tablename__ = "lead_signals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("crm_accounts.id"), nullable=True, index=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("lead_sources.id"), nullable=True)
    signal_type: Mapped[str] = mapped_column(String(80))
    value: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(default=0.0)  # 0..1
    observed_at: Mapped[datetime] = mapped_column(default=_now)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)


class Campaign(Base, TimestampMixin):
    __tablename__ = "lead_campaigns"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    channel: Mapped[str] = mapped_column(String(40), default="email")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|approved|active|paused|closed
    icp_profile: Mapped[dict] = mapped_column(JSON, default=dict)
    budget_brl: Mapped[float] = mapped_column(default=0.0)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    legal_reviewed: Mapped[bool] = mapped_column(default=False)
    start_at: Mapped[datetime | None] = mapped_column(nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(nullable=True)


class CampaignMember(Base, TimestampMixin):
    __tablename__ = "lead_campaign_members"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("lead_campaigns.id"), index=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("crm_accounts.id"), nullable=True)
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("crm_contacts.id"), nullable=True)
    stage: Mapped[str] = mapped_column(String(40), default="company_discovery")
    disposition: Mapped[str] = mapped_column(String(30), default="research_required", index=True)
    icp_fit: Mapped[float] = mapped_column(default=0.0)
    solution_fit: Mapped[float] = mapped_column(default=0.0)
    buying_readiness: Mapped[float] = mapped_column(default=0.0)
    evidence_confidence: Mapped[float] = mapped_column(default=0.0)
    __table_args__ = (
        UniqueConstraint("campaign_id", "contact_id", name="uq_campaign_contact"),
    )


class OutreachMessage(Base, TimestampMixin):
    __tablename__ = "outreach_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("lead_campaigns.id"), nullable=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("crm_contacts.id"))
    channel: Mapped[str] = mapped_column(String(40), default="email")
    subject: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|approved|sent|replied|stopped
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    reply_class: Mapped[str] = mapped_column(String(40), default="")


class SuppressionEntry(Base, TimestampMixin):
    """Opt-out and do-not-contact list. Never bypassed by campaign logic."""

    __tablename__ = "suppression_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="email")  # email|phone|domain|cnpj
    value: Mapped[str] = mapped_column(String(255), index=True)
    reason: Mapped[str] = mapped_column(String(60), default="opt_out")
    __table_args__ = (UniqueConstraint("org_id", "kind", "value", name="uq_suppression_org_value"),)


# --- Deterministic rules ------------------------------------------------------


def can_contact(
    *,
    channel: str,
    contact_allowed: bool,
    opt_out: bool,
    suppressed: bool,
    campaign_approved: bool,
    campaign_legal_reviewed: bool,
    whatsapp_authorized: bool = False,
    email_verified: bool = True,
    source_allowed_for_outreach: bool = True,
) -> tuple[bool, str]:
    """Single gate before any outreach. Unknown channels fail closed."""
    if channel not in CHANNELS:
        return False, "unsupported channel"
    if not source_allowed_for_outreach:
        return False, "source not allowed for outreach"
    if opt_out or suppressed:
        return False, "suppressed or opted out"
    if not contact_allowed:
        return False, "contact not allowed"
    if not campaign_approved:
        return False, "campaign not approved"
    if not campaign_legal_reviewed:
        return False, "campaign not legally reviewed"
    if channel == "whatsapp_business" and not whatsapp_authorized:
        return False, "no authorised WhatsApp conversation"
    if channel == "email" and not email_verified:
        return False, "unverified email must not be labelled verified"
    return True, "eligible"


def human_approval_required(message_kind: str) -> bool:
    """Pricing, contracts, new campaign strategy and unsupported claims."""
    return message_kind in {"pricing", "contract", "new_strategy", "unsupported_claim"}


def stop_sequence(reply_class: str) -> bool:
    return reply_class in {"reply", "opt_out", "unsubscribe", "bounce", "negative"}


def channel_priority(channel: str) -> int:
    return CHANNEL_PRIORITY.get(channel, 99)


def can_transition_stage(current: str, target: str) -> tuple[bool, str]:
    if current not in WORKFLOW_STAGES or target not in WORKFLOW_STAGES:
        return False, "unknown stage"
    if current == target:
        return True, "no-op"
    cur = WORKFLOW_STAGES.index(current)
    tgt = WORKFLOW_STAGES.index(target)
    if tgt == cur + 1:
        return True, "allowed"
    if tgt < cur:
        return True, "rollback allowed"
    return False, f"invalid stage transition: {current} -> {target}"


_LIA_NEXT_ACTION = {
    "qualified": "create_or_update_deal",
    "research_required": "enrich_account",
    "nurture": "nurture_sequence",
    "future_opportunity": "schedule_review",
    "disqualified": "close",
    "restricted": "suppress",
}


def crm_handoff_decision(
    member,
    contact,
    *,
    channel: str = "email",
    suppressed: bool = False,
    campaign_approved: bool = False,
    campaign_legal_reviewed: bool = False,
    whatsapp_authorized: bool = False,
    source_allowed_for_outreach: bool = True,
) -> dict:
    """Deterministic LIA → CRM handoff. Never bypasses the contact gate."""
    from aios.core.crm_intelligence import sales_priority

    disposition = getattr(member, "disposition", "research_required") or "research_required"
    if disposition not in DISPOSITIONS:
        disposition = "research_required"

    allowed, reason = can_contact(
        channel=channel,
        contact_allowed=bool(getattr(contact, "contact_allowed", False)),
        opt_out=bool(getattr(contact, "opt_out_at", None)),
        suppressed=suppressed,
        campaign_approved=campaign_approved,
        campaign_legal_reviewed=campaign_legal_reviewed,
        whatsapp_authorized=whatsapp_authorized,
        email_verified=bool(getattr(contact, "email_verified", False)),
        source_allowed_for_outreach=source_allowed_for_outreach,
    )
    if not allowed and reason in {"suppressed or opted out", "contact not allowed"}:
        disposition = "restricted"

    handoff = allowed and disposition == "qualified"
    score = 0.0
    if allowed:
        score = sales_priority(
            icp_fit=float(getattr(member, "icp_fit", 0.0) or 0.0),
            recency_days=int(getattr(member, "recency_days", 0) or 0),
            attempts=0,
            deal_value=float(getattr(member, "deal_value", 0.0) or 0.0),
            stage_weight=1.0 if disposition == "qualified" else 0.5,
        )

    eng_blocked = disposition in {"future_opportunity", "research_required"}
    return {
        "handoff": handoff,
        "reason": reason,
        "disposition": disposition,
        "channel": channel,
        "next_action": _LIA_NEXT_ACTION[disposition] if allowed else "suppress",
        "score": score,
        "account_id": getattr(member, "account_id", None),
        "contact_id": getattr(contact, "id", None),
        "engineering_work_allowed": not eng_blocked,
        "engineering_work_reason": (
            "Product/Founder review required before engineering work"
            if eng_blocked
            else "no engineering review gate"
        ),
        "provenance": {
            "source": "lia",
            "campaign_id": getattr(member, "campaign_id", None),
            "member_id": getattr(member, "id", None),
            "rules": ["can_contact", "sales_priority", "engineering_work_guard"],
        },
    }
