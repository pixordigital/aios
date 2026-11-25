"""Approval API — human-in-the-loop queue management."""

from fastapi import APIRouter, Depends, HTTPException

from aios.api.deps import get_current_user, verify_org_access_async
from aios.api.security import _require_founder
from aios.core.approval import approval_manager
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Organization, PendingAction as DBAction, User

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

_APPROVER_ROLES = {"admin", "org_admin", "superadmin"}
_REQUESTER_KEYS = ("requested_by", "created_by", "actor_user_id", "human_id")


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
    requester = getattr(row, "requested_by", None) or getattr(row, "created_by", None)
    if not requester:
        requester = next((args[k] for k in _REQUESTER_KEYS if args.get(k)), None)
    return bool(requester) and str(requester) == str(user_id)


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


@router.post("/{action_id}/approve")
async def approve_action(
    action_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    user: User = Depends(get_current_user),
):
    """Approve a pending tool call."""
    await _load_approval_or_404(
        db, action_id=action_id, org_id=user.org_id, user=user, source="api.approvals.approve"
    )
    ok = await approval_manager.approve(action_id, decided_by=user.id, org_id=user.org_id)
    if not ok:
        raise HTTPException(404, "Action not found or already decided")
    return {"status": "approved", "action_id": action_id}


@router.post("/{action_id}/reject")
async def reject_action(
    action_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    user: User = Depends(get_current_user),
):
    """Reject a pending tool call."""
    await _load_approval_or_404(
        db, action_id=action_id, org_id=user.org_id, user=user, source="api.approvals.reject"
    )
    ok = await approval_manager.reject(action_id, decided_by=user.id, org_id=user.org_id)
    if not ok:
        raise HTTPException(404, "Action not found or already decided")
    return {"status": "rejected", "action_id": action_id}
