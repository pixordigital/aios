"""Approval API — human-in-the-loop queue management."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from aios.api.deps import get_current_user, verify_org_access_async
from aios.api.security import _require_founder
from aios.core.approval import approval_manager
from aios.core.audit import log_audit
from aios.core.routine_enforcement import (
    ROUTINE_SIDE_EFFECT_APPROVAL_TOOL,
    ROUTINE_SIDE_EFFECT_DISPATCH_WHITELIST,
)
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Organization, PendingAction as DBAction, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

_APPROVER_ROLES = {"admin", "org_admin", "superadmin"}
_REQUESTER_KEYS = (
    "_requested_by", "requested_by", "created_by", "actor_user_id", "human_id"
)


async def _require_decision_authority(
    db: DatabaseBackend, user: User, org_id: str, *, source: str
) -> None:
    # Founder authority needs the org row; missing/unreadable org must deny.
    try:
        org = await db.get(Organization, org_id)
    except Exception:
        org = None
    if org is None or str(getattr(org, "id", "")) != str(org_id):
        raise HTTPException(403, "approval authority cannot be established")
    role = str(getattr(user, "role", "") or "").strip().lower()
    if role in _APPROVER_ROLES:
        return
    await _require_founder(user, org, db=db, org_id=org_id, source=source)


def _is_self_approval(row: DBAction, user_id: str) -> bool:
    args = row.tool_args if isinstance(row.tool_args, dict) else {}
    requesters = (
        getattr(row, "requested_by", None),
        getattr(row, "created_by", None),
        *(args.get(k) for k in _REQUESTER_KEYS),
    )
    uid = str(user_id)
    return any(r and str(r) == uid for r in requesters)


@router.get("")
async def list_approvals(
    status: str = "pending",
    agent_id: str = "",
    user: User = Depends(get_current_user),
):
    org_id = user.org_id
    pending = approval_manager.get_pending(agent_id=agent_id, org_id=org_id)
    if status != "pending":
        pending = [p for p in pending if p["status"] == status]
    if not pending:
        try:
            from sqlalchemy import select

            from aios.db.backend import db_session
            from aios.db.models import PendingAction as DBAction

            async with db_session() as db:
                # org_id was missing here, so the queue listed every tenant's
                # tool_args and context_summary.
                q = select(DBAction).where(
                    DBAction.status == status, DBAction.org_id == org_id
                )
                if agent_id:
                    q = q.where(DBAction.agent_id == agent_id)
                q = q.order_by(DBAction.created_at.desc()).limit(50)
                rows = (await db.execute(q)).scalars().all()
                pending = [
                    {
                        "id": r.id,
                        "agent_id": r.agent_id,
                        "conversation_id": r.conversation_id,
                        "tool_name": r.tool_name,
                        "tool_args": r.tool_args,
                        "context_summary": r.context_summary,
                        "status": r.status,
                        "created_at": str(r.created_at),
                    }
                    for r in rows
                ]
        except Exception:
            pass
    return {"actions": pending}


async def _load_approval_or_404(
    db: DatabaseBackend, *, action_id: str, org_id: str, user: User, source: str
) -> DBAction:
    from sqlalchemy import select

    row = (await db.execute(select(DBAction).where(DBAction.id == action_id))).scalar_one_or_none()
    await verify_org_access_async(
        org_id,
        row,
        db=db,
        actor_id=user.id,
        source=source,
        payload={"action_id": str(action_id), "resource_type": "PendingAction"},
    )
    await _require_decision_authority(db, user, org_id, source=source)
    if _is_self_approval(row, user.id):
        raise HTTPException(403, "cannot decide own approval request")
    return row


async def _dispatch_routine_side_effect_approval(
    db: DatabaseBackend, *, row: DBAction, action_id: str, decided_by: str
) -> dict:
    """Best-effort dispatch after human approval. Fail closed on bad marker."""
    from sqlalchemy import select

    tool_args = row.tool_args if isinstance(row.tool_args, dict) else {}
    marker = tool_args.get("_routine_approved_action")
    if not isinstance(marker, dict):
        await log_audit(db, row.org_id, "routine_side_effect.dispatch.skipped", "pending_action",
                        user_id=decided_by, resource_id=action_id,
                        details={"reason": "missing_marker"})
        return {"dispatched": False, "reason": "missing_marker"}

    marker_org = str(marker.get("org_id") or "")
    if marker_org != str(row.org_id or ""):
        await log_audit(db, row.org_id, "routine_side_effect.dispatch.denied", "pending_action",
                        user_id=decided_by, resource_id=action_id,
                        details={"reason": "org_mismatch"})
        return {"dispatched": False, "reason": "org_mismatch"}

    dispatch_job = str(marker.get("dispatch_job") or "").strip()
    dispatch_payload = marker.get("dispatch_payload") or {}
    if not dispatch_job:
        await log_audit(db, row.org_id, "routine_side_effect.dispatch.skipped", "pending_action",
                        user_id=decided_by, resource_id=action_id,
                        details={"reason": "no_dispatch_job"})
        return {"dispatched": False, "reason": "no_dispatch_job"}
    if dispatch_job not in {j.rsplit(".", 1)[-1] for j in ROUTINE_SIDE_EFFECT_DISPATCH_WHITELIST}:
        await log_audit(db, row.org_id, "routine_side_effect.dispatch.denied", "pending_action",
                        user_id=decided_by, resource_id=action_id,
                        details={"reason": "job_not_whitelisted", "dispatch_job": dispatch_job})
        return {"dispatched": False, "reason": "job_not_whitelisted"}
    if not isinstance(dispatch_payload, dict):
        await log_audit(db, row.org_id, "routine_side_effect.dispatch.denied", "pending_action",
                        user_id=decided_by, resource_id=action_id,
                        details={"reason": "bad_payload"})
        return {"dispatched": False, "reason": "bad_payload"}

    # Ensure approved human decision is present in DB before dispatch.
    fresh = (
        await db.execute(
            select(DBAction).where(DBAction.id == action_id).execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if not fresh or fresh.status != "approved" or not str(fresh.decided_by or "").strip():
        await log_audit(db, row.org_id, "routine_side_effect.dispatch.denied", "pending_action",
                        user_id=decided_by, resource_id=action_id,
                        details={"reason": "not_human_approved"})
        return {"dispatched": False, "reason": "not_human_approved"}
    if str(fresh.org_id or "") != str(row.org_id or ""):
        await log_audit(db, row.org_id, "routine_side_effect.dispatch.denied", "pending_action",
                        user_id=decided_by, resource_id=action_id,
                        details={"reason": "fresh_org_mismatch"})
        return {"dispatched": False, "reason": "fresh_org_mismatch"}

    payload = dict(dispatch_payload)
    payload.setdefault("org_id", row.org_id)
    # Stamp routine approval context for traceability; enforcement uses DB evidence.
    routine = payload.get("routine") if isinstance(payload.get("routine"), dict) else {}
    routine = dict(routine)
    routine.setdefault("routine_id", marker.get("routine_id"))
    routine.setdefault("idempotency_key", marker.get("idempotency_key"))
    routine.setdefault("approval_fingerprint", marker.get("approved_fingerprint"))
    routine.setdefault("source_type", marker.get("source_type"))
    routine.setdefault("mode", marker.get("mode"))
    routine.setdefault("side_effects", marker.get("side_effects") or [])
    routine.setdefault("approved", True)
    routine.setdefault("approved_action_id", action_id)
    routine.setdefault("approved_by", decided_by)
    payload["routine"] = routine

    full_job = f"aios.tasks.jobs.{dispatch_job}" if "." not in dispatch_job else dispatch_job
    try:
        from aios.tasks.queue import enqueue_job

        await enqueue_job(full_job, payload)
    except Exception as exc:
        await log_audit(db, row.org_id, "routine_side_effect.dispatch.skipped", "pending_action",
                        user_id=decided_by, resource_id=action_id,
                        details={"reason": "enqueue_failed", "error": str(exc)[:200], "dispatch_job": dispatch_job})
        return {"dispatched": False, "reason": "enqueue_failed", "error": str(exc)[:200]}

    await log_audit(db, row.org_id, "routine_side_effect.dispatch.enqueued", "pending_action",
                    user_id=decided_by, resource_id=action_id,
                    details={"dispatch_job": dispatch_job, "routine_id": marker.get("routine_id"),
                             "idempotency_key": marker.get("idempotency_key")})
    return {"dispatched": True, "dispatch_job": dispatch_job}


@router.post("/{action_id}/approve")
async def approve_action(
    action_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    user: User = Depends(get_current_user),
):
    """Approve a pending tool call."""
    row = await _load_approval_or_404(
        db, action_id=action_id, org_id=user.org_id, user=user, source="api.approvals.approve"
    )
    ok = await approval_manager.approve(action_id, decided_by=user.id, org_id=user.org_id)
    if not ok:
        raise HTTPException(404, "Action not found or already decided")

    # Agent pack activation: deterministic apply after approval.
    try:
        from aios.api.agent_packs import apply_agent_pack_activation, ACTIVATE_TOOL, ROLLBACK_TOOL
        from sqlalchemy import select

        fresh = (
            await db.execute(
                select(DBAction).where(DBAction.id == action_id).execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        tool = str(getattr(fresh, "tool_name", "") or row.tool_name or "")
        if fresh and tool in {ACTIVATE_TOOL, ROLLBACK_TOOL}:
            action_kind = "rollback" if tool == ROLLBACK_TOOL else "activation"
            await log_audit(db, user.org_id, f"agent_pack.{action_kind}.approved", "agent_pack_activation",
                            user_id=user.id, resource_id=action_id,
                            details={"tool_name": tool, "action_id": action_id})
            apply_result = await apply_agent_pack_activation(db, fresh)
            if not apply_result.get("ok"):
                await log_audit(db, user.org_id, f"agent_pack.{action_kind}.failed", "agent_pack_activation",
                                user_id=user.id, resource_id=str(apply_result.get("activation_id") or action_id),
                                details={"tool_name": tool, "action_id": action_id, "reason": apply_result.get("reason")})
            return {"status": "approved", "action_id": action_id, "apply": apply_result}
        if fresh and tool == ROUTINE_SIDE_EFFECT_APPROVAL_TOOL:
            dispatch = await _dispatch_routine_side_effect_approval(
                db, row=fresh, action_id=action_id, decided_by=user.id
            )
            return {"status": "approved", "action_id": action_id, "dispatch": dispatch}
    except HTTPException:
        raise
    except Exception:
        logger.exception("approval post-hook failed for %s", action_id)

    return {"status": "approved", "action_id": action_id}


@router.post("/{action_id}/reject")
async def reject_action(
    action_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    user: User = Depends(get_current_user),
):
    """Reject a pending tool call."""
    row = await _load_approval_or_404(
        db, action_id=action_id, org_id=user.org_id, user=user, source="api.approvals.reject"
    )
    ok = await approval_manager.reject(action_id, decided_by=user.id, org_id=user.org_id)
    if not ok:
        raise HTTPException(404, "Action not found or already decided")

    try:
        from aios.api.agent_packs import ACTIVATE_TOOL, ROLLBACK_TOOL, _load_activation_for_action
        from aios.core.audit import log_audit

        tool = str(row.tool_name or "")
        if tool in {ACTIVATE_TOOL, ROLLBACK_TOOL}:
            action_kind = "rollback" if tool == ROLLBACK_TOOL else "activation"
            await log_audit(db, user.org_id, f"agent_pack.{action_kind}.rejected", "agent_pack_activation",
                            user_id=user.id, resource_id=action_id,
                            details={"tool_name": tool, "action_id": action_id})
            fresh = await db.get(DBAction, action_id)
            if fresh:
                activation = await _load_activation_for_action(db, fresh)
                if activation and activation.status == "requested":
                    activation.status = "rejected"
                    activation.decided_by = user.id
                    from datetime import datetime, timezone
                    activation.decided_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    await db.commit()
    except Exception:
        logger.exception("agent pack reject hook failed for %s", action_id)

    return {"status": "rejected", "action_id": action_id}
