"""Swarm API — team swarm config, task dispatch, consensus, shared memory."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from aios.api.deps import get_current_user, get_org_id
from aios.core.swarm import swarm
from aios.db.backend import db_session
from aios.db.models import Agent, Conversation, SwarmTask, Team, User, team_agents

router = APIRouter(prefix="/api/swarms", tags=["swarms"])


async def _team_in_org(team_id: str, org_id: str) -> bool:
    async with db_session() as db:
        return (
            await db.execute(select(Team.id).where(Team.id == team_id, Team.org_id == org_id))
        ).scalar_one_or_none() is not None


async def _agent_in_team_org(agent_id: str, team_id: str, org_id: str) -> bool:
    async with db_session() as db:
        return (
            await db.execute(
                select(team_agents.c.agent_id)
                .join(Agent, Agent.id == team_agents.c.agent_id)
                .where(
                    team_agents.c.team_id == team_id,
                    team_agents.c.agent_id == agent_id,
                    Agent.org_id == org_id,
                )
            )
        ).scalar_one_or_none() is not None


async def _conversation_in_team_org(conversation_id: str, team_id: str, org_id: str) -> bool:
    async with db_session() as db:
        conv = await db.get(Conversation, conversation_id)
        if not conv or conv.org_id != org_id:
            return False
        return not conv.team_id or conv.team_id == team_id


async def _depends_on_in_team_org(depends_on: list[str], team_id: str, org_id: str) -> bool:
    deps = [d for d in depends_on if isinstance(d, str) and d]
    if not deps:
        return True
    async with db_session() as db:
        rows = (
            await db.execute(
                select(SwarmTask.id, SwarmTask.task_id).where(
                    SwarmTask.team_id == team_id,
                    SwarmTask.org_id == org_id,
                    (SwarmTask.id.in_(deps) | SwarmTask.task_id.in_(deps)),
                )
            )
        ).all()
    known = {v for row in rows for v in row if v}
    return all(d in known for d in deps)


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
    cfg = await swarm.get_config(team_id, org_id=org_id)
    if not cfg:
        cfg = await swarm.ensure_config(team_id, org_id)
    if not cfg:
        raise HTTPException(404, "team not found")
    return cfg


@router.patch("/{team_id}/config")
async def update_swarm_config(
    team_id: str,
    body: SwarmConfigUpdate,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    cfg = await swarm.update_config(team_id, org_id=org_id, **fields)
    if not cfg:
        cfg = await swarm.ensure_config(team_id, org_id)
        if not cfg:
            raise HTTPException(404, "team not found")
        cfg = await swarm.update_config(team_id, org_id=org_id, **fields)
    if not cfg:
        raise HTTPException(404, "team not found")
    return cfg


# ── Tasks ──

class DispatchRequest(BaseModel):
    task_type: str = Field(default="agent_call", min_length=1, max_length=64)
    payload: dict = Field(default_factory=dict)
    priority: int = 0
    conversation_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    agent_id: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


@router.post("/{team_id}/dispatch")
async def dispatch_task(
    team_id: str,
    body: DispatchRequest,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    task_type = body.task_type.strip()
    if not task_type:
        raise HTTPException(400, "task_type required")
    if not await _team_in_org(team_id, org_id):
        raise HTTPException(404, "team not found")
    if body.agent_id and not await _agent_in_team_org(body.agent_id, team_id, org_id):
        raise HTTPException(404, "agent not found in team")
    if body.conversation_id and not await _conversation_in_team_org(body.conversation_id, team_id, org_id):
        raise HTTPException(404, "conversation not found")
    deps = [d for d in body.depends_on if isinstance(d, str) and d]
    if body.depends_on and not deps:
        raise HTTPException(400, "depends_on must contain task ids")
    if not await _depends_on_in_team_org(deps, team_id, org_id):
        raise HTTPException(404, "dependency not found")
    task = await swarm.dispatch(
        team_id=team_id, org_id=org_id, task_type=task_type,
        payload=body.payload, priority=body.priority,
        conversation_id=body.conversation_id, depends_on=deps,
        agent_id=body.agent_id, idempotency_key=body.idempotency_key,
    )
    if not task:
        raise HTTPException(404, "team not found")
    return task


async def _task_action_conflict(
    team_id: str, task_id: str, org_id: str, *, action: str, actionable: set[str]
) -> HTTPException:
    existing = await swarm.get_task(task_id, org_id=org_id, team_id=team_id)
    if not existing:
        if not await _team_in_org(team_id, org_id):
            return HTTPException(404, "team not found")
        return HTTPException(404, "task not found")
    if existing.status not in actionable:
        return HTTPException(409, f"task not {action}: status={existing.status}")
    return HTTPException(404, "task not found or not claimable")


@router.post("/{team_id}/tasks/{task_id}/claim")
async def claim_task(
    team_id: str, task_id: str,
    agent_id: str,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    task = await swarm.claim(task_id, agent_id, org_id, team_id=team_id)
    if not task:
        existing = await swarm.get_task(task_id, org_id=org_id, team_id=team_id)
        if not existing:
            if not await _team_in_org(team_id, org_id):
                raise HTTPException(404, "team not found")
            raise HTTPException(404, "task not found")
        if existing.status not in {"queued", "assigned"}:
            raise HTTPException(409, f"task not claimable: status={existing.status}")
        if not await _agent_in_team_org(agent_id, team_id, org_id):
            raise HTTPException(404, "agent not found in team")
        raise HTTPException(404, "task not found or not claimable")
    return task


@router.post("/{team_id}/tasks/{task_id}/complete")
async def complete_task(
    team_id: str, task_id: str,
    result: dict | None = None, error: str = "",
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    task = await swarm.complete(task_id, result=result, error=error, org_id=org_id, team_id=team_id)
    if not task:
        raise await _task_action_conflict(
            team_id, task_id, org_id, action="completable", actionable={"queued", "assigned", "running", "consensus"}
        )
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
    task = await swarm.vote(task_id, agent_id, vote, org_id=org_id, team_id=team_id)
    if not task:
        raise await _task_action_conflict(
            team_id, task_id, org_id, action="votable", actionable={"queued", "assigned", "running", "consensus"}
        )
    return task


@router.get("/{team_id}/tasks")
async def list_swarm_tasks(
    team_id: str, status: str = "", limit: int = Query(20, ge=1, le=100),
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    rows = await swarm.list_tasks(team_id=team_id, status=status, limit=limit, org_id=org_id)
    return {"items": rows, "total": len(rows)}


@router.get("/{team_id}/stats")
async def swarm_stats(
    team_id: str,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    return await swarm.stats(team_id, org_id=org_id)


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
    if not await _team_in_org(team_id, org_id):
        raise HTTPException(404, "team not found")
    if body.sender_id and not await _agent_in_team_org(body.sender_id, team_id, org_id):
        raise HTTPException(404, "agent not found in team")
    msg = await swarm.put_shared(
        team_id=team_id, org_id=org_id, key=body.key,
        content=body.content, sender_id=body.sender_id,
        ttl_seconds=body.ttl_seconds,
    )
    if not msg:
        raise HTTPException(404, "team not found")
    return msg


@router.get("/{team_id}/memory/{key}")
async def get_shared_memory(
    team_id: str, key: str,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    msg = await swarm.get_shared(team_id=team_id, key=key, org_id=org_id)
    if not msg:
        if not await _team_in_org(team_id, org_id):
            raise HTTPException(404, "team not found")
        raise HTTPException(404, "memory key not found or expired")
    return msg
