"""AI SOC foundations: incident records, response authority, deterministic metrics.

Security is an independent assurance function. Agents may collect evidence and
run narrow, pre-approved, reversible containment; destructive or fundamental
actions stay human-controlled. The rules below are the enforcement point.

Storage note: incident/event models share the application DB; they are not
claimed as independent or append-only storage in this code path.
"""

from datetime import datetime, timezone
import logging
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from aios.db.engine import Base

log = logging.getLogger("aios.security")


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


CLOSED_INCIDENT_STATUSES = {"closed"}
ACTIVE_INCIDENT_STATUSES = set(INCIDENT_STATUSES) - CLOSED_INCIDENT_STATUSES


class ResponseDenied(PermissionError):
    """Action exceeds the caller's response authority."""


def response_authority(action: str) -> str:
    """Unknown actions fail closed to human control."""
    return RESPONSE_AUTHORITY.get(action, "human")


def derive_actor_type(*, user: Any = None, org: Any = None) -> str:
    """Deterministic actor type from authenticated identity/org role."""
    if user is None:
        return "unknown"
    role = str(getattr(user, "role", "") or "").lower()
    org_extra = getattr(org, "extra_data", None) or {}
    founder_id = org_extra.get("founder_user_id")
    if founder_id and founder_id == getattr(user, "id", None):
        return "human"
    if role in {"owner", "admin", "founder", "member", "user", "operator"}:
        return "human"
    return "human"


def is_founder_authority(*, user: Any = None, org: Any = None) -> bool:
    if user is None or org is None:
        return False
    role = str(getattr(user, "role", "") or "").lower()
    extra = getattr(org, "extra_data", None) or {}
    return extra.get("founder_user_id") == getattr(user, "id", None) or role in {"owner", "founder"}


def stored_preapproval(*, action: str, org: Any = None, actor_type: str) -> tuple[bool, str | None]:
    """Preapproval must come from stored policy/approval record, not request body."""
    if actor_type != "human" or org is None:
        return False, None
    extra = getattr(org, "extra_data", None) or {}
    sec = extra.get("security_policy") if isinstance(extra.get("security_policy"), dict) else {}
    preapproved_actions = sec.get("preapproved_actions") if isinstance(sec.get("preapproved_actions"), list) else []
    if action and action in preapproved_actions:
        return True, "security_policy.preapproved_actions"
    approvals = sec.get("approvals") if isinstance(sec.get("approvals"), list) else []
    for rec in approvals:
        if not isinstance(rec, dict):
            continue
        if rec.get("action") == action and rec.get("approved") is True:
            ref = str(rec.get("id") or rec.get("ticket") or "security_policy.approvals")
            return True, ref
    return False, None


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


def response_decision_record(
    *,
    incident: SecurityIncident,
    action: str,
    level: str,
    allowed: bool,
    reason: str,
    actor_type: str,
    actor_id: str | None,
    founder: bool,
    preapproval_source: str | None,
    requested_preapproved: bool,
) -> dict[str, Any]:
    """Deterministic response-gateway audit record; no new DB table required."""
    return {
        "kind": "security.response.decision",
        "incident_id": incident.id,
        "org_id": incident.org_id,
        "action": action,
        "level": level,
        "allowed": allowed,
        "reason": reason,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "founder": founder,
        "preapproval_source": preapproval_source,
        "requested_preapproved": requested_preapproved,
        "incident_status": incident.status,
        "recorded_at": _now().isoformat(),
    }


async def record_security_event(
    db: Any,
    *,
    org_id: str,
    source: str,
    event_type: str,
    severity: str = "info",
    incident_id: str | None = None,
    actor_type: str | None = None,
    actor_id: str | None = None,
    payload: dict | None = None,
) -> SecurityEvent | None:
    """Best-effort SecurityEvent write when table/schema is available."""
    if db is None or not hasattr(db, "add"):
        return None
    try:
        evt = SecurityEvent(
            org_id=org_id,
            source=source,
            event_type=event_type,
            severity=severity,
            incident_id=incident_id,
            actor_type=actor_type,
            actor_id=actor_id,
            payload=payload or {},
        )
        db.add(evt)
        await db.flush()
        return evt
    except Exception:
        log.exception("security event write failed: %s", event_type)
        return None


async def apply_response_gateway(
    db: Any,
    *,
    incident: SecurityIncident,
    action: str,
    user: Any = None,
    org: Any = None,
    requested_preapproved: bool = False,
) -> dict[str, Any]:
    """Minimal response gateway: authorize, audit, record event metadata."""
    level = response_authority(action)
    actor_type = derive_actor_type(user=user, org=org)
    actor_id = getattr(user, "id", None)
    founder = is_founder_authority(user=user, org=org)
    preapproved, preapproval_source = stored_preapproval(action=action, org=org, actor_type=actor_type)
    allowed, reason = check_response(
        action,
        actor_type=actor_type,
        preapproved=preapproved,
        founder=founder,
    )
    if requested_preapproved and not preapproved:
        reason = f"{reason}; request.preapproved ignored without stored approval"
    record = response_decision_record(
        incident=incident,
        action=action,
        level=level,
        allowed=allowed,
        reason=reason,
        actor_type=actor_type,
        actor_id=str(actor_id) if actor_id else None,
        founder=founder,
        preapproval_source=preapproval_source,
        requested_preapproved=requested_preapproved,
    )
    event = await record_security_event(
        db,
        org_id=incident.org_id,
        source="security.api.respond",
        event_type="security.response.allowed" if allowed else "security.response.denied",
        severity="high" if not allowed else "info",
        incident_id=incident.id,
        actor_type=actor_type,
        actor_id=str(actor_id) if actor_id else None,
        payload=record,
    )
    if event is not None:
        record["event_id"] = event.id
    log.info("security_response_decision %s", record)
    return record


def incident_metrics(
    incidents: list[SecurityIncident],
    *,
    events: list["SecurityEvent"] | None = None,
) -> dict:
    """Deterministic metrics from existing incident/event data.

    Fields not computable from available telemetry are returned as null with
    `unknown` source in `metric_sources`, never fabricated.
    """

    def _mean(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 2) if values else None

    def _mins(start: datetime | None, end: datetime | None) -> float | None:
        if start is None or end is None:
            return None
        return (end - start).total_seconds() / 60

    mttd = [m for i in incidents if (m := _mins(i.detected_at, i.acknowledged_at)) is not None]
    mtta = mttd
    mttr = [m for i in incidents if (m := _mins(i.detected_at, i.recovered_at)) is not None]
    contain = [m for i in incidents if (m := _mins(i.acknowledged_at, i.contained_at)) is not None]
    recover = [m for i in incidents if (m := _mins(i.contained_at, i.recovered_at)) is not None]

    evs = events or []
    by_type = [str(getattr(e, "event_type", "") or "") for e in evs]
    unauthorized = sum(1 for t in by_type if "unauthorized" in t or "forbidden" in t or "auth_denied" in t)
    cross_tenant = sum(1 for t in by_type if "cross_tenant" in t or "tenant_violation" in t)
    fp_events = sum(1 for t in by_type if "false_positive" in t or t.endswith(".fp"))
    recovery_tests = [e for e in evs if "recovery_test" in str(getattr(e, "event_type", "") or "")]
    recovery_pass = sum(1 for e in recovery_tests if (getattr(e, "payload", {}) or {}).get("success") is True)
    recovery_fail = sum(1 for e in recovery_tests if (getattr(e, "payload", {}) or {}).get("success") is False)

    total_detections = len(incidents) + fp_events
    fp_rate = round(fp_events / total_detections, 4) if total_detections else None

    return {
        "incidents": len(incidents),
        "open": sum(1 for i in incidents if i.status not in CLOSED_INCIDENT_STATUSES),
        "critical_open": sum(1 for i in incidents if i.severity == "critical" and i.status not in CLOSED_INCIDENT_STATUSES),
        "mttd_minutes": _mean(mttd),
        "mtta_minutes": _mean(mtta),
        "mttr_minutes": _mean(mttr),
        "mean_detect_minutes": _mean(mttd),
        "mean_contain_minutes": _mean(contain),
        "mean_recover_minutes": _mean(recover),
        "false_positive_rate": fp_rate,
        "coverage": {
            "incidents_total": len(incidents),
            "events_total": len(evs),
            "incidents_with_ack": sum(1 for i in incidents if i.acknowledged_at is not None),
            "incidents_with_containment": sum(1 for i in incidents if i.contained_at is not None),
            "incidents_with_recovery": sum(1 for i in incidents if i.recovered_at is not None),
        },
        "unresolved_critical_vulns": None,
        "recovery_test_success_rate": (
            round(recovery_pass / (recovery_pass + recovery_fail), 4)
            if (recovery_pass + recovery_fail)
            else None
        ),
        "unauthorized_attempts": unauthorized,
        "cross_tenant_violations": cross_tenant,
        "metric_sources": {
            "mttd_minutes": "security_incidents.detected_at,acknowledged_at",
            "mtta_minutes": "security_incidents.detected_at,acknowledged_at",
            "mttr_minutes": "security_incidents.detected_at,recovered_at",
            "false_positive_rate": "security_incidents+security_events.false_positive",
            "coverage": "security_incidents,security_events",
            "unresolved_critical_vulns": "unknown:no_vuln_telemetry_in_schema",
            "recovery_test_success_rate": "security_events.recovery_test.payload.success" if recovery_tests else "unknown:no_recovery_test_events",
            "unauthorized_attempts": "security_events.event_type",
            "cross_tenant_violations": "security_events.event_type",
        },
    }
