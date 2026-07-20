from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aios.db.engine import get_db
from aios.db.models import Agent, AgentInstance
from aios.schemas import AgentCreate, AgentOut, AgentUpdate
from aios.templates import apply_template
from .deps import get_current_user, get_org_id

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.post("", response_model=AgentOut)
async def create_agent(
    body: AgentCreate,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    # apply template defaults then overlay any explicit overrides
    tpl = apply_template(body.agent_type) if body.agent_type != "custom" else None
    agent = Agent(
        org_id=org_id,
        name=body.name,
        agent_type=body.agent_type,
        system_prompt=body.system_prompt or (tpl.get("system_prompt", "") if tpl else ""),
        llm_config=(tpl.get("llm_config", body.llm_config) if tpl and not body.llm_config.get("model") == "openai/gpt-4o" else body.llm_config),
        tools=body.tools or (tpl.get("tools", []) if tpl else []),
        memory_config=body.memory_config if body.memory_config.get("short_term") else (tpl.get("memory_config", body.memory_config) if tpl else body.memory_config),
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


@router.get("", response_model=list[AgentOut])
async def list_agents(
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    result = await db.execute(
        select(Agent).where(Agent.org_id == org_id).order_by(Agent.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    return agent


@router.put("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: str,
    body: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)

    update_data = body.model_dump(exclude_unset=True)
    for key, val in update_data.items():
        setattr(agent, key, val)
    await db.commit()
    await db.refresh(agent)
    return agent


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    await db.delete(agent)
    await db.commit()
    return {"ok": True}


@router.post("/{agent_id}/deploy", response_model=AgentOut)
async def deploy_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    agent.status = "active"
    instance = AgentInstance(agent_id=agent_id, status="running")
    db.add(instance)
    await db.commit()
    await db.refresh(agent)
    return agent


@router.post("/{agent_id}/stop", response_model=AgentOut)
async def stop_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    agent.status = "draft"
    result = await db.execute(
        select(AgentInstance).where(
            AgentInstance.agent_id == agent_id,
            AgentInstance.status == "running",
        )
    )
    for inst in result.scalars():
        inst.status = "stopped"
    await db.commit()
    await db.refresh(agent)
    return agent
