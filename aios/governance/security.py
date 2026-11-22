"""AI SOC foundations: incident records, response authority, deterministic metrics.

Security is an independent assurance function. Agents may collect evidence and
run narrow, pre-approved, reversible containment; destructive or fundamental
actions stay human-controlled. The rules below are the enforcement point.
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


# action -> authority level
RESPONSE_AUTHORITY = {
    "collect_evidence": "autonomous",
    "rate_limit_reversible": "autonomous",
    "pause_suspicious_agent": "autonomous",
    "quarantine_file": "autonomous",
    "preserve_logs": "autonomous",
    "temporarily_disable_user": "conditional",
    "rotate_credential": "conditional",
    "isolate_container": "conditional",
    "disable_integration": "conditional",
    "restrict_db_route": "conditional",
    "delete_data": "human",
    "destructive_db_restore": "human",
    "permanently_disable_customer": "human",
    "fundamental_policy_change": "human",
    "accept_risk": "human",
}

AUTHORITY_LEVELS = ("autonomous", "conditional", "human")

SEVERITIES = ("info", "low", "medium", "high", "critical")
INCIDENT_STATUSES = ("detected", "investigating", "contained", "eradicated", "recovered", "closed")


class SecurityIncident(Base, TimestampMixin):
    """One incident. Evidence lives in independent storage, not only here."""

    __tablename__ = "security_incidents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    incident_key: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(80), default="")
    severity: Mapped[str] = mapped_column(String(20), default="medium", index=True)
    status: Mapped[str] = mapped_column(String(20), default="detected", index=True)
    detected_at: Mapped[datetime] = mapped_column(default=_now)
    acknowledged_at: Mapped[datetime | None] = mapped_column(nullable=True)
    contained_at: Mapped[datetime | None] = mapped_column(nullable=True)
    recovered_at: Mapped[datetime | None] = mapped_column(nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    personal_data_involved: Mapped[bool] = mapped_column(default=False)
    privacy_handoff_at: Mapped[datetime | None] = mapped_column(nullable=True)
    external_notification_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    timeline: Mapped[list] = mapped_column(JSON, default=list)
    __table_args__ = (UniqueConstraint("org_id", "incident_key", name="uq_security_incident_key"),)


class SecurityEvent(Base, TimestampMixin):
    """Append-only detection telemetry for metrics and investigation."""

    __tablename__ = "security_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    source: Mapped[str] = mapped_column(String(80), default="", index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(20), default="info")
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("security_incidents.id"), nullable=True)
    actor_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


# --- Deterministic rules ------------------------------------------------------


class ResponseDenied(PermissionError):
    """Action exceeds the caller's response authority."""


def response_authority(action: str) -> str:
    """Unknown actions fail closed to human control."""
    return RESPONSE_AUTHORITY.get(action, "human")


def check_response(
    action: str,
    *,
    actor_type: str,
    preapproved: bool = False,
    founder: bool = False,
) -> tuple[bool, str]:
    """Decide whether an actor may run a response action."""
    level = response_authority(action)
    if level == "autonomous":
        return True, "pre-approved autonomous containment"
    if level == "conditional":
        if actor_type == "human" and preapproved:
            return True, "narrow pre-approved conditional action"
        return False, "conditional action needs a human under narrow policy"
    if founder:
        return True, "founder-authorised human action"
    return False, "human-controlled action; founder/authorised human required"


def classify_severity(
    *, cross_tenant: bool, credential_exposure: bool, personal_data: bool, confirmed_impact: bool
) -> str:
    if cross_tenant or (credential_exposure and confirmed_impact):
        return "critical"
    if credential_exposure or personal_data:
        return "high"
    if confirmed_impact:
        return "medium"
    return "low"


def require_privacy_handoff(incident: SecurityIncident, *, now: datetime | None = None) -> bool:
    """Personal-data incidents must reach Privacy; the flag drives the SLA."""
    if not incident.personal_data_involved:
        return False
    if incident.privacy_handoff_at is None:
        incident.privacy_handoff_at = now or _now()
        return True
    return False


def incident_metrics(incidents: list[SecurityIncident]) -> dict:
    """Mean times in minutes, plus coverage counters. Deterministic."""

    def _mean(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 2) if values else None

    def _mins(start: datetime | None, end: datetime | None) -> float | None:
        if start is None or end is None:
            return None
        return (end - start).total_seconds() / 60

    detect = [m for i in incidents if (m := _mins(i.detected_at, i.acknowledged_at)) is not None]
    contain = [m for i in incidents if (m := _mins(i.acknowledged_at, i.contained_at)) is not None]
    recover = [m for i in incidents if (m := _mins(i.contained_at, i.recovered_at)) is not None]
    return {
        "incidents": len(incidents),
        "open": sum(1 for i in incidents if i.status != "closed"),
        "critical_open": sum(1 for i in incidents if i.severity == "critical" and i.status != "closed"),
        "mean_detect_minutes": _mean(detect),
        "mean_contain_minutes": _mean(contain),
        "mean_recover_minutes": _mean(recover),
    }
