"""Privacy & LGPD governance: processing registry + deterministic enforcement.

Design guidance, not legal advice. The rules here decide access mechanically;
a qualified Brazilian privacy professional still validates the registry entries.

Actions evaluate actor, tenant, resource, purpose, legal basis, minimisation,
transfers, retention and approval. Outcomes are allow / deny / require_approval
/ restrict / defer. Missing policy for new or sensitive processing fails closed.
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


LAWFUL_BASES = (
    "consent",
    "contract",
    "legal_obligation",
    "legitimate_interest",
    "public_policy",
    "research",
    "credit_protection",
    "health_protection",
    "life_protection",
)

# Bases that require a documented assessment before use on personal data.
ASSESSED_BASES = ("legitimate_interest", "public_policy", "research", "credit_protection")

PROCESSING_OUTCOMES = ("allow", "deny", "require_approval", "restrict", "defer")

REQUEST_TYPES = ("access", "correction", "deletion", "portability", "objection", "information")
REQUEST_STATUSES = ("received", "verifying", "in_progress", "completed", "rejected", "overdue")


class ProcessingActivity(Base, TimestampMixin):
    """Mandatory processing activity record (LGPD art. 37)."""

    __tablename__ = "processing_activities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    activity_key: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(default=1)
    role: Mapped[str] = mapped_column(String(20), default="controller")  # controller | operator
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    purpose: Mapped[str] = mapped_column(Text, default="")
    data_subjects: Mapped[list] = mapped_column(JSON, default=list)
    data_categories: Mapped[list] = mapped_column(JSON, default=list)
    sensitive_data: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str] = mapped_column(String(255), default="")
    legal_basis: Mapped[str] = mapped_column(String(40), default="")
    legal_basis_evidence: Mapped[str] = mapped_column(Text, default="")
    necessity_assessment: Mapped[str] = mapped_column(Text, default="")
    recipients: Mapped[list] = mapped_column(JSON, default=list)
    vendors: Mapped[list] = mapped_column(JSON, default=list)
    locations: Mapped[list] = mapped_column(JSON, default=list)
    international_transfers: Mapped[list] = mapped_column(JSON, default=list)
    transfer_mechanism: Mapped[str] = mapped_column(String(120), default="")
    notice: Mapped[str] = mapped_column(Text, default="")
    retention_days: Mapped[int] = mapped_column(default=0)
    rights_route: Mapped[str] = mapped_column(String(255), default="")
    safeguards: Mapped[str] = mapped_column(Text, default="")
    ripd_status: Mapped[str] = mapped_column(String(30), default="not_required")
    policy_version: Mapped[str] = mapped_column(String(40), default="")
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|approved|suspended
    __table_args__ = (
        UniqueConstraint("org_id", "activity_key", "version", name="uq_processing_activity_version"),
    )


class PrivacyRequest(Base, TimestampMixin):
    """Individual data-subject rights workflow (not an org export)."""

    __tablename__ = "privacy_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    subject_identifier: Mapped[str] = mapped_column(String(255), index=True)
    request_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="received", index=True)
    received_at: Mapped[datetime] = mapped_column(default=_now)
    due_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    rejection_reason: Mapped[str] = mapped_column(Text, default="")


# --- Deterministic evaluation -------------------------------------------------


def ripd_required(*, sensitive_data: bool, large_scale: bool, high_risk: bool) -> bool:
    return sensitive_data or large_scale or high_risk


def evaluate_processing(
    activity: ProcessingActivity | None,
    *,
    actor_org_id: str,
    tenant_org_id: str,
    action: str,
    purpose: str = "",
    sensitive: bool = False,
    opt_out: bool = False,
    legal_hold: bool = False,
    policy_available: bool = True,
) -> tuple[str, str]:
    """Return (outcome, reason). Deterministic; no LLM may override this."""
    if actor_org_id != tenant_org_id:
        return "deny", "cross-tenant access"
    if activity is None:
        return "deny", "no processing activity record"
    if activity.org_id != tenant_org_id:
        return "deny", "activity belongs to another tenant"
    if not policy_available:
        if sensitive or activity.sensitive_data:
            return "deny", "missing policy for sensitive processing"
        return "defer", "missing policy"
    if activity.status != "approved":
        return "deny", f"activity status is {activity.status}"
    if purpose and activity.purpose and purpose != activity.purpose:
        return "restrict", "purpose mismatch"
    if activity.legal_basis not in LAWFUL_BASES:
        return "deny", "invalid or missing legal basis"
    if activity.legal_basis in ASSESSED_BASES and not activity.legal_basis_evidence.strip():
        return "deny", f"{activity.legal_basis} requires documented assessment"
    if activity.legal_basis == "legitimate_interest" and (sensitive or activity.sensitive_data):
        return "deny", "legitimate interest cannot ground sensitive data"
    if opt_out and action in {"market", "outreach", "communicate"}:
        return "deny", "data subject opted out"
    if legal_hold and action == "delete":
        return "restrict", "legal hold blocks deletion"
    if activity.international_transfers and not activity.transfer_mechanism.strip():
        return "require_approval", "international transfer without mechanism"
    if not activity.necessity_assessment.strip():
        return "require_approval", "necessity/minimisation not assessed"
    if sensitive and not activity.sensitive_data:
        return "require_approval", "sensitive data outside declared categories"
    return "allow", "policy satisfied"


def request_due_at(received_at: datetime, days: int = 15) -> datetime:
    """LGPD requests need a timely answer; 15 days is the internal default."""
    return received_at + timedelta(days=days)


def deletion_targets() -> tuple[str, ...]:
    """Every store a deletion must reach. Vendors are handled per activity."""
    return (
        "crm",
        "messages",
        "transcripts",
        "documents",
        "rag_chunks",
        "embeddings",
        "caches",
        "analytics_extracts",
        "vendors",
    )
