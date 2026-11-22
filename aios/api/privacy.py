"""Privacy & LGPD API: processing activities, deterministic evaluation, rights requests."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from aios.api.deps import get_current_user, get_org_id
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Organization
from aios.governance.privacy import PrivacyRequest, ProcessingActivity
from aios.governance.privacy import evaluate_processing, request_due_at

router = APIRouter(prefix="/api/privacy", tags=["privacy"])


@router.get("/activities")
async def list_activities(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    from sqlalchemy import select

    rows = (await db.execute(select(ProcessingActivity).where(ProcessingActivity.org_id == org_id))).scalars().all()
    items = [
        {
            "id": a.id,
            "activity_key": a.activity_key,
            "purpose": a.purpose,
            "legal_basis": a.legal_basis,
            "status": a.status,
            "sensitive_data": a.sensitive_data,
            "retention_days": a.retention_days,
        }
        for a in rows
    ]
    return {"items": items}


@router.post("/activities")
async def create_activity(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    required = ("activity_key", "purpose", "legal_basis")
    missing = [f for f in required if not str(body.get(f) or "").strip()]
    if missing:
        raise HTTPException(400, f"missing required fields: {', '.join(missing)}")
    if body.get("legal_basis") not in ("consent", "contract", "legal_obligation", "legitimate_interest", "public_policy", "research"):
        raise HTTPException(400, "invalid legal basis")
    activity = ProcessingActivity(
        org_id=org_id,
        activity_key=str(body["activity_key"]),
        purpose=str(body["purpose"]),
        data_subjects=list(body.get("data_subjects") or []),
        data_categories=list(body.get("data_categories") or []),
        sensitive_data=bool(body.get("sensitive_data", False)),
        source=str(body.get("source") or ""),
        legal_basis=str(body["legal_basis"]),
        legal_basis_evidence=str(body.get("legal_basis_evidence") or ""),
        necessity_assessment=str(body.get("necessity_assessment") or ""),
        retention_days=int(body.get("retention_days") or 0),
        rights_route=str(body.get("rights_route") or ""),
        status=str(body.get("status") or "draft"),
    )
    db.add(activity)
    await db.commit()
    await db.refresh(activity)
    return {"id": activity.id, "activity_key": activity.activity_key, "status": activity.status}


@router.post("/evaluate")
async def evaluate(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    activity_key = str(body.get("activity_key") or "")
    if not activity_key:
        raise HTTPException(400, "activity_key required")
    outcome, reason = evaluate_processing(
        None,
        actor_org_id=org_id,
        tenant_org_id=org_id,
        action=str(body.get("action") or "read"),
        purpose=str(body.get("purpose") or ""),
        sensitive=bool(body.get("sensitive", False)),
        opt_out=bool(body.get("opt_out", False)),
        legal_hold=bool(body.get("legal_hold", False)),
        policy_available=bool(body.get("policy_available", True)),
    )
    rows = (await db.execute(_select_by_key(org_id, activity_key))).scalars().all()
    record = rows[-1] if rows else None
    if record is not None:
        outcome, reason = evaluate_processing(
            record,
            actor_org_id=org_id,
            tenant_org_id=org_id,
            action=str(body.get("action") or "read"),
            purpose=str(body.get("purpose") or ""),
            sensitive=bool(body.get("sensitive", False)),
            opt_out=bool(body.get("opt_out", False)),
            legal_hold=bool(body.get("legal_hold", False)),
            policy_available=bool(body.get("policy_available", True)),
        )
    return {"activity_key": activity_key, "outcome": outcome, "reason": reason}


@router.post("/requests")
async def create_request(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    request_type = str(body.get("request_type") or "")
    if request_type not in ("access", "correction", "deletion", "portability", "objection", "information"):
        raise HTTPException(400, "invalid request_type")
    subject = str(body.get("subject_identifier") or "")
    if not subject:
        raise HTTPException(400, "subject_identifier required")
    request = PrivacyRequest(
        org_id=org_id,
        subject_identifier=subject,
        request_type=request_type,
        status="received",
        received_at=datetime.utcnow(),
        due_at=request_due_at(datetime.utcnow(), int(body.get("due_days") or 15)),
        scope=dict(body.get("scope") or {}),
    )
    db.add(request)
    await db.commit()
    await db.refresh(request)
    return {"id": request.id, "status": request.status, "due_at": str(request.due_at)}


def _select_by_key(org_id: str, activity_key: str):
    from sqlalchemy import select

    return select(ProcessingActivity).where(
        ProcessingActivity.org_id == org_id, ProcessingActivity.activity_key == activity_key
    )