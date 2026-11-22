from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Memory, Organization, User
from aios.governance.knowledge import (
    CLASSIFICATIONS,
    KNOWLEDGE_KINDS,
    KnowledgeRecord,
    can_retrieve,
    fact_promotion_allowed,
    hard_delete_eligible,
    validate_provenance,
)
from aios.governance.ocp import DepartmentMember
from .deps import get_current_user, get_org_id

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _is_founder(user: User, org: Organization | None) -> bool:
    if org is None:
        return False
    return (org.extra_data or {}).get("founder_user_id") == user.id or user.role == "owner"


async def _actor_deps(db: DatabaseBackend, user: User) -> set[str]:
    rows = (
        await db.execute(
            select(DepartmentMember.department_id).where(
                DepartmentMember.org_id == user.org_id, DepartmentMember.user_id == user.id
            )
        )
    ).scalars().all()
    return {d for d in rows if d}


async def _record(record_id: str, org_id: str, db: DatabaseBackend) -> KnowledgeRecord:
    record = (
        await db.execute(
            select(KnowledgeRecord).where(
                KnowledgeRecord.id == record_id, KnowledgeRecord.org_id == org_id
            )
        )
    ).scalars().first()
    if record is None:
        raise HTTPException(404, "knowledge record not found")
    return record


@router.get("/records")
async def list_records(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: DatabaseBackend = Depends(get_db_backend),
    user: User = Depends(get_current_user),
):
    rows = (await db.execute(
        select(KnowledgeRecord).where(KnowledgeRecord.org_id == user.org_id)
    )).scalars().all()
    org = await db.get(Organization, user.org_id)
    deps = await _actor_deps(db, user)
    visible = [
        r for r in rows
        if can_retrieve(
            r,
            actor_org_id=user.org_id,
            actor_departments=deps,
            is_founder=_is_founder(user, org),
        )[0]
    ]
    total = len(visible)
    page = visible[offset : offset + limit]
    return {
        "items": [
            {
                "id": r.id, "title": r.title, "kind": r.kind,
                "classification": r.classification, "department_id": r.department_id,
            }
            for r in page
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/records")
async def create_record(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    kind = str(body.get("kind") or "statement")
    classification = str(body.get("classification") or "internal")
    if kind not in KNOWLEDGE_KINDS:
        raise HTTPException(400, "invalid knowledge kind")
    if classification not in CLASSIFICATIONS:
        raise HTTPException(400, "invalid classification")
    title = str(body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title required")
    record = KnowledgeRecord(
        org_id=org_id,
        department_id=body.get("department_id"),
        title=title,
        content=str(body.get("content") or ""),
        kind=kind,
        classification=classification,
        source_type=str(body.get("source_type") or ""),
        source_id=str(body.get("source_id") or ""),
        provenance=dict(body.get("provenance") or {}),
        derived_from=list(body.get("derived_from") or []),
        account_id=body.get("account_id"),
        search_text=str(body.get("search_text") or ""),
    )
    problems = validate_provenance(record)
    if problems:
        raise HTTPException(400, f"provenance invalid: {', '.join(problems)}")
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {"id": record.id, "kind": record.kind, "classification": record.classification}


@router.post("/records/{record_id}/promote")
async def promote_record(
    record_id: str,
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    record = await _record(record_id, org_id, db)
    if not fact_promotion_allowed(record, human_confirmed=bool(body.get("human_confirmed", False))):
        raise HTTPException(400, "human confirmation required for non-fact promotion")
    record.kind = "fact"
    await db.commit()
    return {"id": record.id, "kind": record.kind}


@router.post("/records/{record_id}/soft-delete")
async def soft_delete_record(
    record_id: str,
    user: User = Depends(get_current_user),
    db: DatabaseBackend = Depends(get_db_backend),
):
    record = await _record(record_id, user.org_id, db)
    org = await db.get(Organization, user.org_id)
    if not _is_founder(user, org):
        raise HTTPException(403, "Founder approval required")
    record.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    return {"id": record.id, "deleted": True}


@router.get("/records/{record_id}/delete-eligibility")
async def delete_eligibility(
    record_id: str,
    legal_hold: bool = False,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    record = await _record(record_id, org_id, db)
    return {"eligible": hard_delete_eligible(record, legal_hold=legal_hold)}


@router.get("/search")
async def search(
    q: str = Query(...),
    top_k: int = Query(5, ge=1, le=50),
    db: DatabaseBackend = Depends(get_db_backend),
    user: User = Depends(get_current_user),
):
    from aios.core.rag import search_knowledge_records

    org = await db.get(Organization, user.org_id)
    deps = await _actor_deps(db, user)
    results = await search_knowledge_records(
        user.org_id,
        q,
        top_k=top_k,
        actor_departments=deps,
        is_founder=_is_founder(user, org),
    )
    return {
        "query": q,
        "results": results,
        "count": len(results),
        "source": "knowledge_records",
    }

@router.get("/memories")
async def list_memories(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    rows = (
        await db.execute(
            select(Memory)
            .where(Memory.org_id == org_id)
            .order_by(Memory.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return [
        {"id": r.id, "content": r.content[:600], "type": r.type, "agent_id": r.agent_id, "created_at": str(r.created_at)}
        for r in rows
    ]
