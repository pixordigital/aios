"""Internal finance/legal SOR API.

Read endpoints always available. Mutation endpoints guarded: auth, org scope,
DB approval evidence, idempotency. No external provider integration, no money movement.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from aios.api.deps import get_current_user, get_org_id
from aios.core.approval_evidence import verify_and_consume_approval
from aios.core.finance_sor import (
    FINANCE_ENTITIES,
    FinanceSORAccessError,
    FinanceSORConflictError,
    FinanceSORValidationError,
    get_finance_record,
    get_finance_reconciliation,
    list_finance_reconciliations,
    list_finance_records,
    list_posted_ledger_entries,
    mark_finance_reconciliation,
    post_balanced_ledger_entries,
)
from aios.db.backend import DatabaseBackend, get_db_backend

router = APIRouter(prefix="/api/internal/finance-sor", tags=["finance-sor"])


class LedgerPostingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_entity: str = Field(..., min_length=1)
    source_id: str = Field(..., min_length=1)
    idempotency_key: str = Field(..., min_length=1)
    approval_action_id: str = Field(..., min_length=1)


class ReconciliationMarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity: str = Field(..., min_length=1)
    record_id: str = Field(..., min_length=1)
    state: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    linked_entity: str | None = None
    linked_id: str | None = None
    idempotency_key: str = Field(..., min_length=1)
    approval_action_id: str = Field(..., min_length=1)


def _approval_denied(reason: str, details: dict[str, Any] | None = None) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "error": "approval_required",
            "reason": reason,
            "details": details or {},
        },
    )


def _canon_str(value: Any) -> str:
    return str(value or "").strip()


def _args_match(expected: dict[str, Any]):
    expected_norm = {k: _canon_str(v) if isinstance(v, str) or v is not None else None for k, v in expected.items()}

    def _match(tool_args: Any) -> bool:
        if not isinstance(tool_args, dict):
            return False
        for k, v in expected_norm.items():
            actual = tool_args.get(k)
            actual_norm = _canon_str(actual) if isinstance(actual, str) or actual is not None else None
            if actual_norm != v:
                return False
        return True

    return _match


def _serialize(obj) -> dict:
    data = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if hasattr(val, "isoformat"):
            val = val.isoformat()
        data[col.name] = val
    return data


@router.get("")
async def entities_meta(_user=Depends(get_current_user)):
    return {
        "entities": sorted(FINANCE_ENTITIES.keys()),
        "read_only_get": True,
        "guarded_mutations": ["ledger_postings", "reconciliation_mark"],
    }


@router.get("/reconciliations")
async def list_reconciliations(
    entity: str | None = Query(default=None),
    state: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    _user=Depends(get_current_user),
):
    try:
        items = await list_finance_reconciliations(
            db, org_id=org_id, entity=entity, state=state, limit=limit, offset=offset
        )
    except FinanceSORAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FinanceSORValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": items, "count": len(items)}


@router.get("/reconciliations/{entity}/{record_id}")
async def get_reconciliation(
    entity: str,
    record_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    _user=Depends(get_current_user),
):
    try:
        rec = await get_finance_reconciliation(db, org_id=org_id, entity=entity, record_id=record_id)
    except FinanceSORAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FinanceSORValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return rec


@router.get("/ledger-entries")
async def list_ledger_entries(
    source_entity: str | None = Query(default=None),
    source_id: str | None = Query(default=None),
    posting_key: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    _user=Depends(get_current_user),
):
    try:
        rows = await list_posted_ledger_entries(
            db,
            org_id=org_id,
            source_entity=source_entity,
            source_id=source_id,
            posting_key=posting_key,
            limit=limit,
            offset=offset,
        )
    except FinanceSORAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FinanceSORValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": [_serialize(r) for r in rows], "count": len(rows), "entity": "ledger_entry"}


@router.get("/{entity}")
async def list_entities(
    entity: str,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    _user=Depends(get_current_user),
):
    try:
        rows = await list_finance_records(
            db, org_id=org_id, entity=entity, status=status, limit=limit, offset=offset
        )
    except FinanceSORAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FinanceSORValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"items": [_serialize(r) for r in rows], "count": len(rows), "entity": entity}


@router.get("/{entity}/{record_id}")
async def get_entity(
    entity: str,
    record_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    _user=Depends(get_current_user),
):
    try:
        row = await get_finance_record(db, org_id=org_id, entity=entity, record_id=record_id)
    except FinanceSORAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FinanceSORValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return _serialize(row)


@router.post("/ledger/postings")
async def post_ledger_posting(
    body: LedgerPostingRequest,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    _user=Depends(get_current_user),
):
    expected_args = {
        "source_entity": body.source_entity,
        "source_id": body.source_id,
        "idempotency_key": body.idempotency_key,
    }
    try:
        # Idempotent replay: same posting key+source returns existing without consuming new approval.
        existing = await list_posted_ledger_entries(
            db,
            org_id=org_id,
            source_entity=body.source_entity,
            source_id=body.source_id,
            posting_key=body.idempotency_key,
            limit=10,
            offset=0,
        )
    except FinanceSORAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FinanceSORValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if existing:
        from aios.core.finance_sor import _posting_result  # internal helper; stable behavior

        # list_posted_ledger_entries orders desc; first posting response uses asc.
        ordered = sorted(existing, key=lambda e: (str(getattr(e, "created_at", "") or ""), str(getattr(e, "id", ""))))
        result = _posting_result(ordered, deduped=True)
        result["approval"] = {"reused": True}
        return result

    approval = await verify_and_consume_approval(
        db,
        org_id=str(org_id),
        approval_action_id=body.approval_action_id,
        expected_tool_name={"finance_sor.post_balanced_ledger_entries", "finance_sor.post_ledger_posting"},
        args_match=_args_match(expected_args),
    )
    if not approval.ok:
        await db.rollback()
        raise _approval_denied(approval.reason, approval.details)

    try:
        result = await post_balanced_ledger_entries(
            db,
            org_id=org_id,
            source_entity=body.source_entity,
            source_id=body.source_id,
            idempotency_key=body.idempotency_key,
        )
    except FinanceSORAccessError as exc:
        await db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FinanceSORConflictError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"error": "conflict", "reason": str(exc)}) from exc
    except FinanceSORValidationError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()
    result["approval"] = {
        "approval_action_id": approval.details.get("approval_action_id"),
        "decided_by": approval.details.get("decided_by"),
    }
    return result


@router.post("/reconciliations/mark")
async def mark_reconciliation(
    body: ReconciliationMarkRequest,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    _user=Depends(get_current_user),
):
    expected_args = {
        "entity": body.entity,
        "record_id": body.record_id,
        "state": body.state,
        "reason": body.reason,
        "linked_entity": body.linked_entity,
        "linked_id": body.linked_id,
        "idempotency_key": body.idempotency_key,
    }
    try:
        current = await get_finance_reconciliation(db, org_id=org_id, entity=body.entity, record_id=body.record_id)
    except FinanceSORAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FinanceSORValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    rec = current.get("reconciliation") if isinstance(current, dict) else None
    if isinstance(rec, dict) and _canon_str(rec.get("idempotency_key")) == body.idempotency_key:
        same = (
            _canon_str(rec.get("state")) == body.state.strip().lower()
            and _canon_str(rec.get("reason")) == body.reason.strip()
            and _canon_str(rec.get("linked_entity")) == _canon_str(body.linked_entity).lower()
            and _canon_str(rec.get("linked_id")) == _canon_str(body.linked_id)
        )
        if same:
            return {**current, "ok": True, "deduped": True, "approval": {"reused": True}}
        raise HTTPException(status_code=409, detail={"error": "conflict", "reason": "idempotency key already used for different reconciliation"})

    approval = await verify_and_consume_approval(
        db,
        org_id=str(org_id),
        approval_action_id=body.approval_action_id,
        expected_tool_name={"finance_sor.mark_finance_reconciliation", "finance_sor.mark_reconciliation"},
        args_match=_args_match(expected_args),
    )
    if not approval.ok:
        await db.rollback()
        raise _approval_denied(approval.reason, approval.details)

    try:
        result = await mark_finance_reconciliation(
            db,
            org_id=org_id,
            entity=body.entity,
            record_id=body.record_id,
            state=body.state,
            reason=body.reason,
            linked_entity=body.linked_entity,
            linked_id=body.linked_id,
            idempotency_key=body.idempotency_key,
        )
    except FinanceSORAccessError as exc:
        await db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FinanceSORConflictError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"error": "conflict", "reason": str(exc)}) from exc
    except FinanceSORValidationError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()
    result["approval"] = {
        "approval_action_id": approval.details.get("approval_action_id"),
        "decided_by": approval.details.get("decided_by"),
    }
    return result
