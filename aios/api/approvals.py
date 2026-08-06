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
    """List pending approval actions."""
    pending = approval_manager.get_pending(agent_id=agent_id)
    if status != "pending":
        pending = [p for p in pending if p["status"] == status]
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
