"""Swarm API — team swarm config, task dispatch, consensus, shared memory."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from aios.api.deps import get_current_user, get_org_id
from aios.core.swarm import swarm
from aios.db.models import User

router = APIRouter(prefix="/api/swarms", tags=["swarms"])


# ── Config ──

class SwarmConfigUpdate(BaseModel):
    swarm_mode: str | None = None
    task_distribution: str | None = None
    consensus_threshold: float | None = Field(default=None, ge=0, le=1)
    max_concurrent_tasks: int | None = None
    broadcast_enabled: bool | None = None
    shared_memory_enabled: bool | None = None


@router.get("/{team_id}/config")
async def get_swarm_config(
    team_id: str,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    cfg = await swarm.get_config(team_id)
    if not cfg:
        cfg = await swarm.ensure_config(team_id, org_id)
    return cfg


@router.patch("/{team_id}/config")
async def update_swarm_config(
    team_id: str,
    body: SwarmConfigUpdate,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    cfg = await swarm.update_config(team_id, **fields)
    if not cfg:
        cfg = await swarm.ensure_config(team_id, org_id)
        cfg = await swarm.update_config(team_id, **fields)
    return cfg


# ── Tasks ──

class DispatchRequest(BaseModel):
    task_type: str = Field(default="agent_call")
    payload: dict = Field(default_factory=dict)
    priority: int = 0
    conversation_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    agent_id: str | None = None


@router.post("/{team_id}/dispatch")
async def dispatch_task(
    team_id: str,
    body: DispatchRequest,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    task = await swarm.dispatch(
        team_id=team_id, org_id=org_id, task_type=body.task_type,
        payload=body.payload, priority=body.priority,
        conversation_id=body.conversation_id, depends_on=body.depends_on,
        agent_id=body.agent_id,
    )
    return task


@router.post("/{team_id}/tasks/{task_id}/claim")
async def claim_task(
    team_id: str, task_id: str,
    agent_id: str,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    task = await swarm.claim(task_id, agent_id)
    if not task:
        raise HTTPException(404, "task not found or not claimable")
    return task


@router.post("/{team_id}/tasks/{task_id}/complete")
async def complete_task(
    team_id: str, task_id: str,
    result: dict | None = None, error: str = "",
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    task = await swarm.complete(task_id, result=result, error=error)
    if not task:
        raise HTTPException(404, "task not found")
    return task


@router.post("/{team_id}/tasks/{task_id}/vote")
async def consensus_vote(
    team_id: str, task_id: str,
    agent_id: str, vote: str,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    if vote not in ("approve", "reject", "abstain"):
        raise HTTPException(400, "vote must be approve|reject|abstain")
    task = await swarm.vote(task_id, agent_id, vote)
    if not task:
        raise HTTPException(404, "task not found")
    return task


@router.get("/{team_id}/tasks")
async def list_swarm_tasks(
    team_id: str, status: str = "", limit: int = Query(20, ge=1, le=100),
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    rows = await swarm.list_tasks(team_id=team_id, status=status, limit=limit)
    return {"items": rows, "total": len(rows)}


@router.get("/{team_id}/stats")
async def swarm_stats(
    team_id: str,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    return await swarm.stats(team_id)


# ── Shared memory ──

class SharedPut(BaseModel):
    key: str = Field(min_length=1, max_length=255)
    content: dict = Field(default_factory=dict)
    ttl_seconds: int = Field(default=3600, ge=60)
    sender_id: str | None = None


@router.post("/{team_id}/memory")
async def put_shared_memory(
    team_id: str, body: SharedPut,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    msg = await swarm.put_shared(
        team_id=team_id, org_id=org_id, key=body.key,
        content=body.content, sender_id=body.sender_id,
        ttl_seconds=body.ttl_seconds,
    )
    return msg


@router.get("/{team_id}/memory/{key}")
async def get_shared_memory(
    team_id: str, key: str,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    msg = await swarm.get_shared(team_id=team_id, key=key)
    if not msg:
        raise HTTPException(404, "memory key not found or expired")
    return msg
