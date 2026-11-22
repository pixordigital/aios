"""AI SOC API: security incidents, governed response gateway, metrics, events."""

from datetime import datetime, timezone
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from aios.api.deps import get_current_user, get_org_id
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Organization
from aios.governance.security import (
    RESPONSE_AUTHORITY,
    SECURITY_METRIC_EVENT_TYPES,
    SecurityEvent,
    SecurityIncident,
    apply_response_gateway,
    emit_security_metric_event,
    incident_metrics,
    is_founder_authority,
    record_cross_tenant_block_if_mismatch,
    record_security_event,
    require_privacy_handoff,
)

router = APIRouter(prefix="/api/security", tags=["security"])
log = logging.getLogger("aios.security.api")

VALID_STATUSES = {"detected", "investigating", "contained", "eradicated", "recovered", "closed"}
VALID_SEVERITIES = {"info", "low", "medium", "high", "critical"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _get_incident(
    db: DatabaseBackend,
    org_id: str,
    incident_id: str,
    *,
    actor_type: str | None = None,
    actor_id: str | None = None,
    source: str = "security.api.incident_lookup",
) -> SecurityIncident:
    incident = await db.get(SecurityIncident, incident_id)
    if incident is None or incident.org_id != org_id:
        evt = await record_cross_tenant_block_if_mismatch(
            db,
            org_id=org_id,
            resource=incident,
            source=source,
            actor_type=actor_type,
            actor_id=actor_id,
            payload={"incident_id": str(incident_id)},
        )
        if evt is not None:
            await db.commit()
        raise HTTPException(404, "incident not found")
    return incident


def _require_founder(user: Any, org: Organization | None) -> None:
    if not is_founder_authority(user=user, org=org):
        raise HTTPException(403, "Founder/owner authority required")


def _security_policy(org: Organization | None) -> dict[str, Any]:
    extra = getattr(org, "extra_data", None) or {}
    sec = extra.get("security_policy")
    return dict(sec) if isinstance(sec, dict) else {}


def _normalized_preapproved_actions(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise HTTPException(400, "preapproved_actions must be a list")
    out: list[str] = []
    for item in value:
        action = str(item or "").strip()
        if not action:
            raise HTTPException(400, "preapproved_actions entries must be non-empty strings")
        if action not in RESPONSE_AUTHORITY:
            raise HTTPException(400, f"unknown action: {action}")
        if action not in out:
            out.append(action)
    return out


def _normalized_approvals(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise HTTPException(400, "approvals must be a list")
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise HTTPException(400, "approval entries must be objects")
        action = str(item.get("action") or "").strip()
        if not action:
            raise HTTPException(400, "approval.action required")
        if action not in RESPONSE_AUTHORITY:
            raise HTTPException(400, f"unknown action: {action}")
        rec: dict[str, Any] = {"action": action, "approved": bool(item.get("approved", False))}
        for key in ("id", "ticket", "note"):
            if item.get(key) is not None:
                text = str(item.get(key)).strip()
                if text:
                    rec[key] = text
        out.append(rec)
    return out


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
    actor_type = "human"
    actor_id = str(getattr(user, "id", "") or "") or None
    incident = await _get_incident(
        db,
        org_id,
        incident_id,
        actor_type=actor_type,
        actor_id=actor_id,
        source="security.api.respond",
    )
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
    actor_id = str(getattr(user, "id", "") or "") or None
    incident = await _get_incident(
        db,
        org_id,
        incident_id,
        actor_type="human",
        actor_id=actor_id,
        source="security.api.incident_close",
    )
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
    metric = str(body.get("metric") or "").strip()
    event_type = str(body.get("event_type") or "").strip()
    if not event_type and not metric:
        raise HTTPException(400, "event_type or metric required")
    severity = str(body.get("severity") or "info")
    if severity not in VALID_SEVERITIES:
        raise HTTPException(400, f"invalid severity: {severity}")
    incident_id = body.get("incident_id")
    if incident_id:
        incident = await db.get(SecurityIncident, str(incident_id))
        if incident is None or incident.org_id != org_id:
            evt = await record_cross_tenant_block_if_mismatch(
                db,
                org_id=org_id,
                resource=incident,
                source="security.api.event_ingest",
                actor_type="human",
                actor_id=str(getattr(user, "id", "") or "") or None,
                payload={"incident_id": str(incident_id)},
            )
            if evt is not None:
                await db.commit()
            raise HTTPException(404, "incident not found")
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    metric = str(body.get("metric") or "").strip()
    if metric:
        if metric not in SECURITY_METRIC_EVENT_TYPES:
            raise HTTPException(400, f"invalid metric: {metric}")
        evt = await emit_security_metric_event(
            db,
            org_id=org_id,
            metric=metric,
            source=str(body.get("source") or "security.api.ingest")[:80],
            severity=severity,
            incident_id=str(incident_id) if incident_id else None,
            actor_type="human",
            actor_id=getattr(user, "id", None),
            payload=payload,
        )
    else:
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
    return {"id": evt.id, "event_type": evt.event_type, "metric": metric or None, "stored": True}


def _preapproval_payload(org: Organization | None) -> dict[str, Any]:
    sec = _security_policy(org)
    actions = sec.get("preapproved_actions")
    approvals = sec.get("approvals")
    return {
        "preapproved_actions": [str(a) for a in actions if str(a).strip()] if isinstance(actions, list) else [],
        "approvals": [dict(r) for r in approvals if isinstance(r, dict)] if isinstance(approvals, list) else [],
        "storage": "org.extra_data.security_policy (shared app DB; not independent/append-only storage)",
    }


async def _save_preapprovals(
    *,
    db: DatabaseBackend,
    org: Organization,
    user: Any,
    preapproved_actions: list[str],
    approvals: list[dict[str, Any]],
) -> dict[str, Any]:
    extra = dict(getattr(org, "extra_data", None) or {})
    sec = dict(extra.get("security_policy") if isinstance(extra.get("security_policy"), dict) else {})
    before = _preapproval_payload(org)
    sec["preapproved_actions"] = preapproved_actions
    sec["approvals"] = approvals
    sec["updated_at"] = _now().isoformat()
    sec["updated_by"] = str(getattr(user, "id", ""))
    extra["security_policy"] = sec
    org.extra_data = extra
    await record_security_event(
        db,
        org_id=org.id,
        source="security.api.preapprovals",
        event_type="security.policy.preapprovals_updated",
        severity="info",
        actor_type="human",
        actor_id=getattr(user, "id", None),
        payload={"before": before, "after": {"preapproved_actions": preapproved_actions, "approvals": approvals}},
    )
    await db.commit()
    await db.refresh(org)
    return _preapproval_payload(org)


@router.get("/preapprovals")
async def get_preapprovals(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    org = await db.get(Organization, org_id)
    _require_founder(user, org)
    return _preapproval_payload(org)


@router.put("/preapprovals")
async def put_preapprovals(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(404, "org not found")
    _require_founder(user, org)
    current = _preapproval_payload(org)
    actions = (
        _normalized_preapproved_actions(body["preapproved_actions"])
        if "preapproved_actions" in body
        else list(current["preapproved_actions"])
    )
    approvals = (
        _normalized_approvals(body["approvals"])
        if "approvals" in body
        else list(current["approvals"])
    )
    return await _save_preapprovals(db=db, org=org, user=user, preapproved_actions=actions, approvals=approvals)


@router.post("/preapprovals/actions")
async def add_preapproved_action(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(404, "org not found")
    _require_founder(user, org)
    action = str(body.get("action") or "").strip()
    if not action:
        raise HTTPException(400, "action required")
    if action not in RESPONSE_AUTHORITY:
        raise HTTPException(400, f"unknown action: {action}")
    current = _preapproval_payload(org)
    actions = list(current["preapproved_actions"])
    if action not in actions:
        actions.append(action)
    return await _save_preapprovals(
        db=db, org=org, user=user, preapproved_actions=actions, approvals=current["approvals"]
    )


@router.delete("/preapprovals/actions/{action}")
async def remove_preapproved_action(
    action: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(404, "org not found")
    _require_founder(user, org)
    action = str(action or "").strip()
    if action not in RESPONSE_AUTHORITY:
        raise HTTPException(400, f"unknown action: {action}")
    current = _preapproval_payload(org)
    actions = [a for a in current["preapproved_actions"] if a != action]
    return await _save_preapprovals(
        db=db, org=org, user=user, preapproved_actions=actions, approvals=current["approvals"]
    )


@router.post("/preapprovals/approvals")
async def add_preapproval_record(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(404, "org not found")
    _require_founder(user, org)
    recs = _normalized_approvals([body])
    rec = recs[0]
    current = _preapproval_payload(org)
    approvals = list(current["approvals"])
    rec_id = str(rec.get("id") or "").strip()
    replaced = False
    if rec_id:
        for i, existing in enumerate(approvals):
            if str(existing.get("id") or "").strip() == rec_id:
                approvals[i] = rec
                replaced = True
                break
    if not replaced:
        approvals.append(rec)
    return await _save_preapprovals(
        db=db, org=org, user=user, preapproved_actions=current["preapproved_actions"], approvals=approvals
    )


@router.delete("/preapprovals/approvals/{approval_id}")
async def remove_preapproval_record(
    approval_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(404, "org not found")
    _require_founder(user, org)
    target = str(approval_id or "").strip()
    if not target:
        raise HTTPException(400, "approval_id required")
    current = _preapproval_payload(org)
    approvals = [r for r in current["approvals"] if str(r.get("id") or "").strip() != target]
    if len(approvals) == len(current["approvals"]):
        raise HTTPException(404, "approval not found")
    return await _save_preapprovals(
        db=db, org=org, user=user, preapproved_actions=current["preapproved_actions"], approvals=approvals
    )
