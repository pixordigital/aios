from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Agent, AgentVersion
from aios.schemas import BaseModel
from .deps import get_current_user, get_org_id

router = APIRouter(prefix="/api/agents", tags=["agent-versions"])

class VersionOut(BaseModel):
    id: str
    agent_id: str
    version: int
    name: str
    system_prompt: str
    llm_config: dict
    tools: list
    agent_type: str
    change_note: str
    created_at: str | None = None

@router.post("/{agent_id}/publish")
async def publish_version(agent_id: str, body: dict = {}, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    max_v = (await db.execute(select(func.max(AgentVersion.version)).where(AgentVersion.agent_id == agent_id))).scalar() or 0
    v = AgentVersion(agent_id=agent.id, org_id=org_id, version=max_v + 1, name=agent.name, system_prompt=agent.system_prompt, llm_config=dict(agent.llm_config or {}), tools=list(agent.tools or []), memory_config=dict(agent.memory_config or {}), governance_config=dict(agent.governance_config or {}), agent_type=agent.agent_type, change_note=body.get("note") or body.get("change_note") or "")
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return v

@router.get("/{agent_id}/versions", response_model=list[VersionOut])
async def list_versions(agent_id: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), limit: int = Query(20, ge=1, le=100)):
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    res = await db.execute(select(AgentVersion).where(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version.desc()).limit(limit))
    return res.scalars().all()

@router.post("/{agent_id}/versions/{version_id}/rollback")
async def rollback_version(agent_id: str, version_id: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    ver = await db.get(AgentVersion, version_id)
    if not ver or ver.agent_id != agent_id:
        raise HTTPException(404)
    agent.name = ver.name
    agent.system_prompt = ver.system_prompt
    agent.llm_config = dict(ver.llm_config or {})
    agent.tools = list(ver.tools or [])
    agent.memory_config = dict(ver.memory_config or {})
    agent.governance_config = dict(ver.governance_config or {})
    agent.agent_type = ver.agent_type
    await db.commit()
    await db.refresh(agent)
    max_v = (await db.execute(select(func.max(AgentVersion.version)).where(AgentVersion.agent_id == agent_id))).scalar() or 0
    new_v = AgentVersion(agent_id=agent.id, org_id=org_id, version=max_v + 1, name=agent.name, system_prompt=agent.system_prompt, llm_config=dict(agent.llm_config or {}), tools=list(agent.tools or []), memory_config=dict(agent.memory_config or {}), governance_config=dict(agent.governance_config or {}), agent_type=agent.agent_type, change_note=f"rollback to v{ver.version}")
    db.add(new_v)
    await db.commit()
    return {"ok": True, "agent": {"id": agent.id, "name": agent.name}, "rolled_back_to": ver.version, "new_version": new_v.version}

@router.get("/{agent_id}/versions/{version_id}")
async def get_version(agent_id: str, version_id: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    ver = await db.get(AgentVersion, version_id)
    if not ver or ver.agent_id != agent_id or ver.org_id != org_id:
        raise HTTPException(404)
    return ver
