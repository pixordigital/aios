from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aios.db.engine import get_db
from aios.db.models import Agent, Team, team_agents
from aios.schemas import TeamAssignRequest, TeamCreate, TeamOut
from .deps import get_org_id

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.post("", response_model=TeamOut)
async def create_team(
    body: TeamCreate,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
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
    return team


@router.get("", response_model=list[TeamOut])
async def list_teams(
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    result = await db.execute(
        select(Team).where(Team.org_id == org_id).order_by(Team.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{team_id}", response_model=TeamOut)
async def get_team(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    team = await db.get(Team, team_id)
    if not team or team.org_id != org_id:
        raise HTTPException(404)
    return team


@router.delete("/{team_id}")
async def delete_team(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    team = await db.get(Team, team_id)
    if not team or team.org_id != org_id:
        raise HTTPException(404)
    await db.delete(team)
    await db.commit()
    return {"ok": True}


@router.post("/{team_id}/agents", response_model=TeamOut)
async def assign_agents(
    team_id: str,
    body: TeamAssignRequest,
    db: AsyncSession = Depends(get_db),
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
    return team
