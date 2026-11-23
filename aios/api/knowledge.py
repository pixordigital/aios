import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Memory, Organization, User
from aios.governance.knowledge import (
    CLASSIFICATIONS,
    KNOWLEDGE_KINDS,
    KnowledgeGrant,
    KnowledgeRecord,
    can_retrieve,
    fact_promotion_allowed,
    hard_delete_eligible,
    validate_provenance,
)
from aios.governance.ocp import DepartmentMember
from .deps import get_current_user, get_org_id, verify_org_access_async

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

# Full-org load + Python ACL filter is a perf hotspot. Scan bounded rows only;
# page correctness guaranteed within scanned set, truncation surfaced in response.
KNOWLEDGE_RECORD_SCAN_LIMIT = 2000


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


async def _record(
    record_id: str,
    org_id: str,
    db: DatabaseBackend,
    *,
    actor_id: str | None = None,
    actor_type: str | None = "human",
    source: str = "knowledge.api.record_lookup",
) -> KnowledgeRecord:
    record = await db.get(KnowledgeRecord, record_id)
    try:
        await verify_org_access_async(
            org_id,
            record,
            db=db,
            actor_id=actor_id,
            actor_type=actor_type,
            source=source,
            payload={"record_id": str(record_id)},
        )
    except HTTPException:
        if record is not None and record.org_id != org_id:
            await db.commit()
        raise
    return record


@router.get("/records")
async def list_records(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: DatabaseBackend = Depends(get_db_backend),
    user: User = Depends(get_current_user),
):
    # Bounded scan: full-org load + Python ACL filter is perf hotspot.
    # Correctness preserved for returned page within scanned set; truncation surfaced.
    scan_limit = KNOWLEDGE_RECORD_SCAN_LIMIT
    rows = (
        await db.execute(
            select(KnowledgeRecord)
            .where(KnowledgeRecord.org_id == user.org_id)
            .order_by(KnowledgeRecord.created_at.desc(), KnowledgeRecord.id.desc())
            .limit(scan_limit + 1)
        )
    ).scalars().all()
    truncated = len(rows) > scan_limit
    if truncated:
        rows = rows[:scan_limit]
        logger.warning(
            "knowledge.records.scan_truncated org=%s user=%s scan_limit=%d",
            user.org_id,
            user.id,
            scan_limit,
        )

    org = await db.get(Organization, user.org_id)
    deps = await _actor_deps(db, user)
    visible = [
        r
        for r in rows
        if can_retrieve(
            r,
            actor_org_id=user.org_id,
            actor_departments=deps,
            is_founder=_is_founder(user, org),
        )[0]
    ]
    total_visible_scanned = len(visible)
    page = visible[offset : offset + limit]
    total_exact = not truncated
    return {
        "items": [
            {
                "id": r.id,
                "title": r.title,
                "kind": r.kind,
                "classification": r.classification,
                "department_id": r.department_id,
            }
            for r in page
        ],
        # Compat: total = visible count within scanned set. Exact only when not truncated.
        "total": total_visible_scanned,
        "total_scanned_visible": total_visible_scanned,
        "total_exact": total_exact,
        "total_note": (
            "total is exact visible count"
            if total_exact
            else "total is visible count within scanned set; scan truncated, true total unknown"
        ),
        "limit": limit,
        "offset": offset,
        "scanned": len(rows),
        "scan_limit": scan_limit,
        "truncated": truncated,
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


@router.post("/ingest")
async def ingest_document(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    user: User = Depends(get_current_user),
):
    """Split a governed document into cited chunks. Bounded; no vector index."""
    from aios.governance.knowledge import knowledge_citation

    org = await db.get(Organization, user.org_id)
    if not _is_founder(user, org):
        raise HTTPException(403, "Founder approval required for knowledge ingestion")
    kind = str(body.get("kind") or "statement")
    classification = str(body.get("classification") or "internal")
    if kind not in KNOWLEDGE_KINDS or classification not in CLASSIFICATIONS:
        raise HTTPException(400, "invalid knowledge kind or classification")
    title = str(body.get("title") or "").strip()
    content = str(body.get("content") or "")
    source_type = str(body.get("source_type") or "").strip()
    if not title or not content.strip() or not source_type:
        raise HTTPException(400, "title, content and source_type required")
    source_id = str(body.get("source_id") or "").strip()
    chunk_size = body.get("chunk_size", 1200)
    max_chunks = body.get("max_chunks", 50)
    if not isinstance(chunk_size, int) or not 200 <= chunk_size <= 4000:
        raise HTTPException(400, "chunk_size must be 200..4000")
    if not isinstance(max_chunks, int) or not 1 <= max_chunks <= 100:
        raise HTTPException(400, "max_chunks must be 1..100")

    words = content.split()
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for word in words:
        if size + len(word) + 1 > chunk_size and current:
            chunks.append(" ".join(current))
            current, size = [], 0
        current.append(word)
        size += len(word) + 1
    if current:
        chunks.append(" ".join(current))
    if len(chunks) > max_chunks:
        raise HTTPException(413, f"document exceeds max_chunks={max_chunks}")

    records = []
    for index, chunk in enumerate(chunks):
        record = KnowledgeRecord(
            org_id=user.org_id,
            department_id=body.get("department_id"),
            title=f"{title} [{index + 1}/{len(chunks)}]",
            content=chunk,
            kind=kind,
            classification=classification,
            source_type=source_type,
            source_id=source_id,
            provenance={
                **dict(body.get("provenance") or {}),
                "ingestion": "document_chunk",
                "chunk_index": index,
                "chunk_count": len(chunks),
            },
            derived_from=list(body.get("derived_from") or []),
            account_id=body.get("account_id"),
            search_text=chunk,
        )
        problems = validate_provenance(record)
        if problems:
            raise HTTPException(400, f"provenance invalid: {', '.join(problems)}")
        db.add(record)
        records.append(record)
    await db.commit()
    for record in records:
        await db.refresh(record)
    from aios.core.rag import RAG_STATUS, store_knowledge_vectors

    if RAG_STATUS["vector"]:
        from aios.core.memory import _embed

        await store_knowledge_vectors(records, [_embed(r.content) for r in records])
    return {
        "count": len(records),
        "chunks": [{"id": r.id, "title": r.title, "citation": knowledge_citation(r)} for r in records],
    }


@router.post("/grants")
async def create_grant(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    user: User = Depends(get_current_user),
):
    """Founder-only explicit grant to a confidential record in own org."""
    org = await db.get(Organization, user.org_id)
    if not _is_founder(user, org):
        raise HTTPException(403, "Founder approval required to grant knowledge access")
    record_id = str(body.get("record_id") or "").strip()
    user_id = str(body.get("user_id") or "").strip()
    if not record_id or not user_id:
        raise HTTPException(400, "record_id and user_id required")
    record = await db.get(KnowledgeRecord, record_id)
    if record is None:
        raise HTTPException(404, "record not found")
    await verify_org_access_async(
        user.org_id,
        record,
        db=db,
        actor_id=user.id,
        source="api.knowledge.create_grant.record",
        payload={"record_id": record_id},
    )
    grantee = await db.get(User, user_id)
    if grantee is None:
        raise HTTPException(404, "user not found")
    await verify_org_access_async(
        user.org_id,
        grantee,
        db=db,
        actor_id=user.id,
        source="api.knowledge.create_grant.grantee",
        payload={"user_id": user_id},
    )
    expires_at = None
    if body.get("expires_at") is not None:
        try:
            expires_at = datetime.fromisoformat(str(body["expires_at"]).replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, "expires_at must be ISO-8601")
        if expires_at.tzinfo:
            expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)
    grant = KnowledgeGrant(
        org_id=user.org_id,
        user_id=user_id,
        record_id=record_id,
        granted_by=user.id,
        reason=str(body.get("reason") or "")[:1000],
        expires_at=expires_at,
    )
    db.add(grant)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(409, "grant already exists")
    await db.refresh(grant)
    return {"id": grant.id, "record_id": record_id, "user_id": user_id, "expires_at": grant.expires_at}


@router.post("/grants/{grant_id}/revoke")
async def revoke_grant(
    grant_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    user: User = Depends(get_current_user),
):
    org = await db.get(Organization, user.org_id)
    if not _is_founder(user, org):
        raise HTTPException(403, "Founder approval required to revoke knowledge access")
    grant = await db.get(KnowledgeGrant, grant_id)
    if grant is None:
        raise HTTPException(404, "grant not found")
    await verify_org_access_async(
        user.org_id,
        grant,
        db=db,
        actor_id=user.id,
        source="api.knowledge.revoke_grant",
        payload={"grant_id": grant_id},
    )
    if grant.revoked_at is None:
        grant.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.commit()
    return {"id": grant.id, "revoked_at": grant.revoked_at}


@router.post("/records/{record_id}/promote")
async def promote_record(
    record_id: str,
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    record = await _record(record_id, org_id, db, source="knowledge.api.promote")
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
    record = await _record(
        record_id, user.org_id, db, actor_id=user.id, source="knowledge.api.soft_delete"
    )
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
    record = await _record(record_id, org_id, db, source="knowledge.api.delete_eligibility")
    return {"eligible": hard_delete_eligible(record, legal_hold=legal_hold)}


@router.get("/search")
async def search(
    q: str = Query(...),
    top_k: int = Query(5, ge=1, le=50),
    db: DatabaseBackend = Depends(get_db_backend),
    user: User = Depends(get_current_user),
):
    from aios.core.rag import search_knowledge_records

    started = time.perf_counter()
    org = await db.get(Organization, user.org_id)
    deps = await _actor_deps(db, user)
    results = await search_knowledge_records(
        user.org_id,
        q,
        top_k=top_k,
        actor_departments=deps,
        is_founder=_is_founder(user, org),
    )
    logger.info(
        "knowledge.search org=%s user=%s top_k=%d returned=%d ms=%.2f",
        user.org_id,
        user.id,
        top_k,
        len(results),
        (time.perf_counter() - started) * 1000,
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
