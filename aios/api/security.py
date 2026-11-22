"""AI SOC API: security incidents, governed response gateway, metrics, events."""

from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from aios.api.deps import get_current_user, get_org_id
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Organization
from aios.governance.security import (
    SecurityEvent,
    SecurityIncident,
    apply_response_gateway,
    incident_metrics,
    record_security_event,
    require_privacy_handoff,
)

router = APIRouter(prefix="/api/security", tags=["security"])
log = logging.getLogger("aios.security.api")

VALID_STATUSES = {"detected", "investigating", "contained", "eradicated", "recovered", "closed"}
VALID_SEVERITIES = {"info", "low", "medium", "high", "critical"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _get_incident(db: DatabaseBackend, org_id: str, incident_id: str) -> SecurityIncident:
    incident = await db.get(SecurityIncident, incident_id)
    if incident is None or incident.org_id != org_id:
        raise HTTPException(404, "incident not found")
    return incident


@router.get("/incidents")
async def list_incidents(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    rows = (await db.execute(select(SecurityIncident).where(SecurityIncident.org_id == org_id))).scalars().all()
    return {
        "items": [
            {
                "id": i.id,
                "incident_key": i.incident_key,
                "title": i.title,
                "severity": i.severity,
                "status": i.status,
                "category": i.category,
                "personal_data_involved": i.personal_data_involved,
            }
            for i in rows
        ]
    }


@router.post("/incidents")
async def create_incident(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    title = str(body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title required")
    severity = str(body.get("severity") or "medium")
    if severity not in VALID_SEVERITIES:
        raise HTTPException(400, f"invalid severity: {severity}")
    incident = SecurityIncident(
        org_id=org_id,
        incident_key=str(body.get("incident_key") or f"inc-{abs(hash((org_id, title, _now().isoformat())))}"),
        title=title,
        category=str(body.get("category") or "appsec"),
        severity=severity,
        status="detected",
        personal_data_involved=bool(body.get("personal_data_involved", False)),
    )
    db.add(incident)
    await db.flush()
    await record_security_event(
        db,
        org_id=org_id,
        source="security.api.incidents",
        event_type="security.incident.created",
        severity=severity,
        incident_id=incident.id,
        actor_type="human",
        actor_id=getattr(user, "id", None),
        payload={"title": title, "category": incident.category},
    )
    await db.commit()
    await db.refresh(incident)
    return {"id": incident.id, "status": incident.status, "severity": incident.severity}


@router.post("/incidents/{incident_id}/respond")
async def respond(
    incident_id: str,
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    incident = await _get_incident(db, org_id, incident_id)
    if incident.status == "closed":
        raise HTTPException(409, "incident is closed")
    action = str(body.get("action") or "").strip()
    if not action:
        raise HTTPException(400, "action required")

    org = await db.get(Organization, org_id)
    decision = await apply_response_gateway(
        db,
        incident=incident,
        action=action,
        user=user,
        org=org,
        requested_preapproved=bool(body.get("preapproved", False)),
    )

    handoff = False
    if incident.personal_data_involved:
        handoff = require_privacy_handoff(incident, now=_now())
        if handoff:
            await record_security_event(
                db,
                org_id=org_id,
                source="security.api.respond",
                event_type="security.privacy.handoff_required",
                severity="high",
                incident_id=incident.id,
                actor_type=decision.get("actor_type"),
                actor_id=decision.get("actor_id"),
                payload={"privacy_handoff_at": incident.privacy_handoff_at.isoformat() if incident.privacy_handoff_at else None},
            )

    incident.timeline = list(incident.timeline or []) + [decision]
    incident.updated_at = _now()
    await db.commit()
    return {
        "action": action,
        "level": decision["level"],
        "allowed": decision["allowed"],
        "reason": decision["reason"],
        "actor_type": decision["actor_type"],
        "preapproval_source": decision["preapproval_source"],
        "privacy_handoff_required": handoff,
        "event_id": decision.get("event_id"),
    }


@router.post("/incidents/{incident_id}/close")
async def close_incident(
    incident_id: str,
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    incident = await _get_incident(db, org_id, incident_id)
    target = str(body.get("status") or "closed")
    if target not in VALID_STATUSES:
        raise HTTPException(400, f"invalid status: {target}")
    if incident.status == "closed" and target == "closed":
        return {"id": incident.id, "status": incident.status, "changed": False}

    incident.status = target
    now = _now()
    if target == "closed":
        incident.closed_at = now
    elif target == "contained":
        incident.contained_at = incident.contained_at or now
    elif target == "recovered":
        incident.recovered_at = incident.recovered_at or now
    elif target == "investigating":
        incident.acknowledged_at = incident.acknowledged_at or now
    incident.updated_at = now

    await record_security_event(
        db,
        org_id=org_id,
        source="security.api.incidents",
        event_type="security.incident.status_changed",
        severity=incident.severity,
        incident_id=incident.id,
        actor_type="human",
        actor_id=getattr(user, "id", None),
        payload={"status": target},
    )
    await db.commit()
    return {"id": incident.id, "status": incident.status, "changed": True}


@router.get("/metrics")
async def metrics(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    incidents = (
        await db.execute(select(SecurityIncident).where(SecurityIncident.org_id == org_id))
    ).scalars().all()
    events = []
    try:
        events = (
            await db.execute(select(SecurityEvent).where(SecurityEvent.org_id == org_id))
        ).scalars().all()
    except Exception:
        log.warning("security events unavailable for metrics; returning incident-only metrics")
    return incident_metrics(list(incidents), events=list(events))


@router.get("/events")
async def list_events(
    incident_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    stmt = select(SecurityEvent).where(SecurityEvent.org_id == org_id)
    if incident_id:
        stmt = stmt.where(SecurityEvent.incident_id == incident_id)
    if event_type:
        stmt = stmt.where(SecurityEvent.event_type == event_type)
    stmt = stmt.order_by(SecurityEvent.created_at.desc()).limit(limit)
    try:
        rows = (await db.execute(stmt)).scalars().all()
    except Exception as exc:
        raise HTTPException(503, f"security events unavailable: {type(exc).__name__}")
    return {
        "items": [
            {
                "id": e.id,
                "source": e.source,
                "event_type": e.event_type,
                "severity": e.severity,
                "incident_id": e.incident_id,
                "actor_type": e.actor_type,
                "actor_id": e.actor_id,
                "payload": e.payload,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in rows
        ]
    }


@router.post("/events")
async def ingest_event(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    event_type = str(body.get("event_type") or "").strip()
    if not event_type:
        raise HTTPException(400, "event_type required")
    severity = str(body.get("severity") or "info")
    if severity not in VALID_SEVERITIES:
        raise HTTPException(400, f"invalid severity: {severity}")
    incident_id = body.get("incident_id")
    if incident_id:
        incident = await db.get(SecurityIncident, str(incident_id))
        if incident is None or incident.org_id != org_id:
            raise HTTPException(404, "incident not found")
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    evt = await record_security_event(
        db,
        org_id=org_id,
        source=str(body.get("source") or "security.api.ingest")[:80],
        event_type=event_type[:80],
        severity=severity,
        incident_id=str(incident_id) if incident_id else None,
        actor_type="human",
        actor_id=getattr(user, "id", None),
        payload=payload,
    )
    if evt is None:
        raise HTTPException(503, "security event storage unavailable")
    await db.commit()
    return {"id": evt.id, "event_type": evt.event_type, "stored": True}
