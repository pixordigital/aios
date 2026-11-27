"""Controlled internal API for fail-closed business execution."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from aios.api.deps import get_current_user, get_org_id
from aios.config import settings
from aios.core.business_execution import ExecutionDenied
from aios.core.business_execution_service import (
    execute_controlled_business_action,
    is_business_idempotency_durable,
)
from aios.db.backend import DatabaseBackend, get_db_backend

router = APIRouter(prefix="/api/internal/business-execution", tags=["business-execution"])


class BusinessExecutionRequest(BaseModel):
    adapter: str = Field(..., min_length=1)
    action: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    side_effect: bool = True


@router.post("/execute")
async def execute_business_action(
    body: BusinessExecutionRequest,
    request: Request,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    _user=Depends(get_current_user),
):
    """Execute a business action through controlled fail-closed registry.

    Approval/config comes from server settings; caller cannot self-approve.
    """

    payload = dict(body.payload or {})
    payload.setdefault("org_id", org_id)
    payload_org = str(payload.get("org_id") or "").strip()
    if payload_org != str(org_id):
        raise HTTPException(status_code=403, detail="payload.org_id must match authenticated org")

    audit_events: list[dict[str, Any]] = []

    def audit_callback(event: dict[str, Any]) -> None:
        item = dict(event)
        item.setdefault("org_id", org_id)
        audit_events.append(item)

    store = getattr(request.app.state, "business_idempotency_store", None)
    try:
        result = execute_controlled_business_action(
            adapter=body.adapter,
            action=body.action,
            payload=payload,
            idempotency_key=body.idempotency_key,
            side_effect=body.side_effect,
            settings=settings,
            db=db,
            audit_callback=audit_callback,
            idempotency_store=store,
        )
    except ExecutionDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return {
        "ok": result.ok,
        "adapter": result.adapter,
        "action": result.action,
        "idempotency_key": result.idempotency_key,
        "status": result.status,
        "detail": result.detail,
        "data": result.data,
        "audit": audit_events,
        "idempotency_durable": is_business_idempotency_durable(store),
    }
