"""Approval API — human-in-the-loop queue management."""

from fastapi import APIRouter, Depends, HTTPException

from aios.api.deps import get_current_user
from aios.core.approval import approval_manager
from aios.db.models import User

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.get("")
async def list_approvals(
    status: str = "pending",
    agent_id: str = "",
    user: User = Depends(get_current_user),
):
    pending = approval_manager.get_pending(agent_id=agent_id)
    if status != "pending":
        pending = [p for p in pending if p["status"] == status]
    if not pending:
        try:
            from sqlalchemy import select

            from aios.db.backend import db_session
            from aios.db.models import PendingAction as DBAction

            async with db_session() as db:
                q = select(DBAction).where(DBAction.status == status)
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


@router.post("/{action_id}/approve")
async def approve_action(
    action_id: str,
    user: User = Depends(get_current_user),
):
    """Approve a pending tool call."""
    ok = approval_manager.approve(action_id, decided_by=user.id)
    if not ok:
        raise HTTPException(404, "Action not found or already decided")
    return {"status": "approved", "action_id": action_id}


@router.post("/{action_id}/reject")
async def reject_action(
    action_id: str,
    user: User = Depends(get_current_user),
):
    """Reject a pending tool call."""
    ok = approval_manager.reject(action_id, decided_by=user.id)
    if not ok:
        raise HTTPException(404, "Action not found or already decided")
    return {"status": "rejected", "action_id": action_id}
