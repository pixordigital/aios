"""AI SOC API: security incidents and governed response authority."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from aios.api.deps import get_current_user, get_org_id
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Organization
from aios.governance.security import SecurityIncident
from aios.governance.security import RESPONSE_AUTHORITY, check_response, require_privacy_handoff

from sqlalchemy import select

router = APIRouter(prefix="/api/security", tags=["security"])

def _is_founder(user, org) -> bool:
    if user is None or org is None:
        return False
    return (org.extra_data or {}).get("founder_user_id") == user.id or user.role == "owner"


@router.get("/incidents")
async def list_incidents(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    rows = (await db.execute(select(SecurityIncident).where(SecurityIncident.org_id == org_id))).scalars().all()
    return {"items": [{"id": i.id, "incident_key": i.incident_key, "title": i.title, "severity": i.severity, "status": i.status} for i in rows]}


@router.post("/incidents")
async def create_incident(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    title = str(body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title required")
    incident = SecurityIncident(
        org_id=org_id,
        incident_key=str(body.get("incident_key") or f"inc-{abs(hash(title))}"),
        title=title,
        category=str(body.get("category") or "appsec"),
        severity=str(body.get("severity") or "medium"),
        status="detected",
        personal_data_involved=bool(body.get("personal_data_involved", False)),
    )
    db.add(incident)
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
    incident = await db.get(SecurityIncident, incident_id)
    if incident is None or incident.org_id != org_id:
        raise HTTPException(404, "incident not found")
    action = str(body.get("action") or "")
    level = RESPONSE_AUTHORITY.get(action, "human")
    allowed, reason = check_response(
        action,
        actor_type=str(body.get("actor_type") or "human"),
        preapproved=bool(body.get("preapproved", False)),
        founder=_is_founder(user, await db.get(Organization, org_id)),
    )
    handoff = require_privacy_handoff(incident, now=None) if incident.personal_data_involved else False
    return {"action": action, "level": level, "allowed": allowed, "reason": reason, "privacy_handoff_required": handoff}


@router.post("/incidents/{incident_id}/close")
async def close_incident(
    incident_id: str,
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    incident = await db.get(SecurityIncident, incident_id)
    if incident is None or incident.org_id != org_id:
        raise HTTPException(404, "incident not found")
    incident.status = str(body.get("status") or "closed")
    if str(incident.status) == "closed":
        incident.closed_at = datetime.utcnow()
    await db.commit()
    return {"id": incident.id, "status": incident.status}
