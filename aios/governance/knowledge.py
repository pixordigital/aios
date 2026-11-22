"""Organizational knowledge: provenance-tagged records and permission-aware retrieval.

A vector index is a retrieval layer, not the source of truth. Retrieval filters
deterministically by tenant, department, classification and grants; the LLM never
decides whether an actor may read a record.
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


KNOWLEDGE_KINDS = ("fact", "statement", "inference", "decision", "historical")
CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")


class KnowledgeRecord(Base, TimestampMixin):
    """One searchable unit with source provenance. Derived summaries link back."""

    __tablename__ = "knowledge_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(20), default="statement", index=True)
    classification: Mapped[str] = mapped_column(String(20), default="internal", index=True)
    source_type: Mapped[str] = mapped_column(String(60), default="")
    source_id: Mapped[str] = mapped_column(String(120), default="")
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    derived_from: Mapped[list] = mapped_column(JSON, default=list)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("crm_accounts.id"), nullable=True, index=True)
    retention_until: Mapped[datetime | None] = mapped_column(nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    search_text: Mapped[str] = mapped_column(Text, default="")  # full-text companion


# --- Deterministic access -----------------------------------------------------


def knowledge_text_score(record: KnowledgeRecord, query: str) -> float:
    """Deterministic lexical score over governed record text. No embeddings."""
    q = (query or "").strip().lower()
    if not q:
        return 0.0
    terms = [t for t in q.split() if t]
    if not terms:
        return 0.0
    hay = " ".join(
        [record.title or "", record.content or "", record.search_text or ""]
    ).lower()
    score = 0.0
    for t in terms:
        count = hay.count(t)
        if count:
            score += 1.0 + min(count, 5) * 0.1
    title = (record.title or "").lower()
    for t in terms:
        if t in title:
            score += 0.5
    return score


def knowledge_citation(record: KnowledgeRecord) -> dict:
    return {
        "record_id": record.id,
        "title": record.title,
        "kind": record.kind,
        "classification": record.classification,
        "department_id": record.department_id,
        "source_type": record.source_type,
        "source_id": record.source_id,
        "provenance": dict(record.provenance or {}),
        "derived_from": list(record.derived_from or []),
        "account_id": record.account_id,
    }


def can_retrieve(
    record: KnowledgeRecord,
    *,
    actor_org_id: str,
    actor_departments: set[str],
    is_founder: bool = False,
    granted_record_ids: set[str] | None = None,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Fail closed on tenant mismatch, deletion, expiry and classification."""
    now = now or _now()
    if record.deleted_at is not None:
        return False, "deleted"
    if record.retention_until is not None and record.retention_until < now:
        return False, "retention expired"
    if record.org_id != actor_org_id:
        return False, "cross-tenant access"
    if is_founder:
        return True, "founder access"
    if record.classification == "restricted":
        return False, "restricted classification"
    if record.classification == "confidential":
        allowed = granted_record_ids or set()
        return (record.id in allowed, "confidential; explicit grant required")
    if record.department_id and record.department_id not in actor_departments:
        return False, "outside department scope"
    return True, "allowed"


def filter_retrievable(records: list[KnowledgeRecord], **kwargs) -> list[KnowledgeRecord]:
    return [r for r in records if can_retrieve(r, **kwargs)[0]]


def validate_provenance(record: KnowledgeRecord) -> list[str]:
    """Every inference/derived summary must point at its sources."""
    problems = []
    if not record.source_type.strip() and not record.derived_from:
        problems.append("missing source provenance")
    if record.kind in {"inference", "decision"} and not record.derived_from:
        problems.append("inference/decision must list derived_from sources")
    return problems


def fact_promotion_allowed(record: KnowledgeRecord, *, human_confirmed: bool) -> bool:
    """A meeting statement or AI inference never silently becomes a fact."""
    if record.kind == "fact":
        return True
    return record.kind in {"statement", "inference"} and human_confirmed


def hard_delete_eligible(record: KnowledgeRecord, *, legal_hold: bool) -> bool:
    return not legal_hold and record.retention_until is not None and record.retention_until < _now()
