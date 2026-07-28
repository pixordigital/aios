from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from aios.core.audit import log_audit
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Agent, Team, team_agents
from aios.schemas import TeamAssignRequest, TeamCreate, TeamOut
from .deps import get_current_user, get_org_id

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.post("", response_model=TeamOut)
async def create_team(
    body: TeamCreate,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    team = Team(
        org_id=org_id,
        name=body.name,
        routing_strategy=body.routing_strategy,
        extra_data=body.extra_data,
    )
    db.add(team)
    await db.commit()
    await db.refresh(team)
    await log_audit(db, org_id, "team.create", "team", user_id=user.id, resource_id=team.id, details={"name": team.name})
    return team


@router.get("", response_model=list[TeamOut])
async def list_teams(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    result = await db.execute(
        select(Team).where(Team.org_id == org_id).order_by(Team.created_at.desc()).limit(limit).offset(offset)
    )
    return result.scalars().all()


@router.get("/{team_id}", response_model=TeamOut)
async def get_team(
    team_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    team = await db.get(Team, team_id)
    if not team or team.org_id != org_id:
        raise HTTPException(404)
    return team


@router.delete("/{team_id}")
async def delete_team(
    team_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    team = await db.get(Team, team_id)
    if not team or team.org_id != org_id:
        raise HTTPException(404)
    await log_audit(db, org_id, "team.delete", "team", user_id=user.id, resource_id=team_id, details={"name": team.name})
    await db.delete(team)
    await db.commit()
    return {"ok": True}


@router.post("/{team_id}/agents")
async def assign_agents(
    team_id: str,
    body: TeamAssignRequest,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    team = await db.get(Team, team_id)
    if not team or team.org_id != org_id:
        raise HTTPException(404)

    result = await db.execute(
        select(Agent).where(
            Agent.id.in_(body.agent_ids),
            Agent.org_id == org_id,
        )
    )
    agents = result.scalars().all()
    team.agents = agents
    await db.commit()
    await db.refresh(team)
    return {
        "id": team.id,
        "name": team.name,
        "routing_strategy": team.routing_strategy,
        "extra_data": team.extra_data,
        "org_id": team.org_id,
        "agents": [{"id": a.id, "name": a.name, "agent_type": a.agent_type} for a in team.agents],
        "created_at": str(team.created_at) if team.created_at else None,
    }
