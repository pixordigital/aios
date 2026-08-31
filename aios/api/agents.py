from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy import select
import json

from aios.core.audit import log_audit
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Agent, AgentInstance
from aios.schemas import AgentCreate, AgentOut, AgentUpdate
from aios.templates import apply_template
from .deps import get_current_user, get_org_id

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.post("", response_model=AgentOut)
async def create_agent(
    body: AgentCreate,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
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

    await log_audit(db, org_id, "agent.create", "agent", user_id=user.id, resource_id=agent.id)

    return agent


@router.get("", response_model=list[AgentOut])
async def list_agents(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    result = await db.execute(
        select(Agent).where(Agent.org_id == org_id).order_by(Agent.created_at.desc()).limit(limit).offset(offset)
    )
    return result.scalars().all()


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
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
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)

    update_data = body.model_dump(exclude_unset=True)
    if "llm_config" in update_data and isinstance(update_data["llm_config"], dict):
        merged = dict(agent.llm_config or {})
        merged.update(update_data["llm_config"])
        agent.llm_config = merged
        update_data.pop("llm_config")
    for key, val in update_data.items():
        setattr(agent, key, val)
    await db.commit()
    await db.refresh(agent)

    return agent


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    await log_audit(db, org_id, "agent.delete", "agent", user_id=user.id, resource_id=agent_id, details={"name": agent.name})
    await db.delete(agent)
    await db.commit()
    return {"ok": True}


@router.post("/{agent_id}/deploy", response_model=AgentOut)
async def deploy_agent(
    agent_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    from aios.core.agent_health import health_tracker

    if not health_tracker.is_available(agent_id):
        raise HTTPException(
            409,
            detail=f"agent {agent.name} circuit breaker open (stopped). Reset health first.",
        )
    from aios.config import PLANS
    from aios.db.models import Organization

    org = await db.get(Organization, org_id)
    plan = ((org.extra_data or {}).get("plan", "free") if org else "free")
    if plan not in ("unlimited",):
        limits = PLANS.get(plan, PLANS["free"])
        cnt = (
            await db.execute(
                select(Agent).where(Agent.org_id == org_id, Agent.status == "active")
            )
        ).scalars().all()
        if len(cnt) >= limits.get("max_agents", 2) and agent.status != "active":
            raise HTTPException(
                403, detail=f"quota max_agents {limits['max_agents']} for {plan}"
            )
    prev_active = agent.status == "active"
    agent.status = "active"
    import datetime

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if not prev_active:
        instance = AgentInstance(
            agent_id=agent_id,
            org_id=org_id,
            status="running",
            extra_data={"deploy": "blue", "deployed_at": now_iso, "deployed_by": user.id},
        )
        db.add(instance)
    else:
        instance = AgentInstance(
            agent_id=agent_id,
            org_id=org_id,
            status="running",
            extra_data={
                "deploy": "green",
                "canary": True,
                "deployed_at": now_iso,
                "deployed_by": user.id,
            },
        )
        db.add(instance)
    await log_audit(
        db,
        org_id,
        "agent.deploy",
        "agent",
        user_id=user.id,
        resource_id=agent_id,
        details={"name": agent.name, "blue_green": "green" if prev_active else "blue"},
    )
    await db.commit()
    await db.refresh(agent)
    try:
        from aios.tasks.queue import enqueue_task

        await enqueue_task(
            "aios.tasks.jobs.agent_run",
            {
                "agent_id": agent_id,
                "conv_id": f"health_{agent_id}",
                "text": "health check",
                "org_id": org_id,
            },
        )
    except Exception:
        pass
    try:
        health_tracker.record_success(agent_id)
    except Exception:
        pass
    return agent


@router.post("/{agent_id}/canary/promote")
async def promote_canary(
    agent_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    rows = (
        await db.execute(
            select(AgentInstance).where(AgentInstance.agent_id == agent_id, AgentInstance.status == "running")
        )
    ).scalars().all()
    canary = next((r for r in rows if (r.extra_data or {}).get("canary")), None)
    if not canary:
        raise HTTPException(400, detail="no canary deployment found")
    canary.extra_data = {**(canary.extra_data or {}), "canary": False, "promoted_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}
    for r in rows:
        if r.id != canary.id:
            r.status = "stopped"
    await log_audit(db, org_id, "agent.canary.promote", "agent", user_id=user.id, resource_id=agent_id)
    await db.commit()
    return {"ok": True, "promoted": canary.id}


@router.post("/{agent_id}/canary/rollback")
async def rollback_canary(
    agent_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    rows = (
        await db.execute(
            select(AgentInstance).where(AgentInstance.agent_id == agent_id, AgentInstance.status == "running")
        )
    ).scalars().all()
    canary = next((r for r in rows if (r.extra_data or {}).get("canary")), None)
    if not canary:
        raise HTTPException(400, detail="no canary found")
    canary.status = "stopped"
    prev = next((r for r in rows if r.id != canary.id and r.status == "stopped"), None)
    if prev:
        prev.status = "running"
    await log_audit(db, org_id, "agent.canary.rollback", "agent", user_id=user.id, resource_id=agent_id)
    await db.commit()
    return {"ok": True, "rolled_back": canary.id}


@router.post("/{agent_id}/health/reset")
async def reset_agent_health(
    agent_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    from aios.core.agent_health import health_tracker

    health_tracker.reset(agent_id)
    await log_audit(db, org_id, "agent.health.reset", "agent", user_id=user.id, resource_id=agent_id)
    return {"ok": True, "status": health_tracker.get_status(agent_id)}


@router.post("/{agent_id}/stop", response_model=AgentOut)
async def stop_agent(
    agent_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
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
    await log_audit(db, org_id, "agent.stop", "agent", user_id=user.id, resource_id=agent_id, details={"name": agent.name})
    await db.commit()
    await db.refresh(agent)
    return agent


# ─── Agent Export / Import / Fleet Push ───


@router.get("/{agent_id}/export")
async def export_agent(
    agent_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    """Export agent config as JSON — portable across AIOS instances."""
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)
    return {
        "name": agent.name,
        "agent_type": agent.agent_type,
        "system_prompt": agent.system_prompt,
        "llm_config": agent.llm_config,
        "tools": agent.tools,
        "memory_config": agent.memory_config,
        "governance_config": agent.governance_config,
    }


@router.post("/import")
async def import_agent(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Import agent config from exported JSON. Creates new agent on this instance."""
    required = ["name", "llm_config"]
    for field in required:
        if field not in body:
            raise HTTPException(422, f"Missing required field: {field}")

    agent = Agent(
        org_id=org_id,
        name=body["name"],
        agent_type=body.get("agent_type", "custom"),
        system_prompt=body.get("system_prompt", ""),
        llm_config=body["llm_config"],
        tools=body.get("tools", []),
        memory_config=body.get("memory_config", {}),
        governance_config=body.get("governance_config", {}),
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)

    await log_audit(db, org_id, "agent.import", "agent", user_id=user.id, resource_id=agent.id, details={"name": agent.name})
    return agent


@router.post("/{agent_id}/push")
async def push_agent_to_fleet(
    agent_id: str,
    target_instance_ids: list[str] = Body(...),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Push agent config to remote fleet instances."""
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)

    from aios.db.models import RemoteInstance
    results = []

    for instance_id in target_instance_ids:
        inst = await db.get(RemoteInstance, instance_id)
        if not inst or not inst.is_active:
            results.append({"instance_id": instance_id, "status": "skipped", "reason": "not found or inactive"})
            continue

        try:
            import httpx
            headers = {"Content-Type": "application/json"}
            if inst.api_key:
                headers["Authorization"] = f"Bearer {inst.api_key}"

            export_data = {
                "name": agent.name,
                "agent_type": agent.agent_type,
                "system_prompt": agent.system_prompt,
                "llm_config": agent.llm_config,
                "tools": agent.tools,
                "memory_config": agent.memory_config,
                "governance_config": agent.governance_config,
            }

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{inst.base_url}/api/agents/import",
                    headers=headers,
                    json=export_data,
                )
                if resp.status_code == 200:
                    results.append({"instance_id": instance_id, "status": "ok"})
                    await log_audit(db, org_id, "agent.push", "agent", user_id=user.id,
                                   resource_id=agent_id, details={"instance": inst.name, "status": "ok"})
                else:
                    results.append({"instance_id": instance_id, "status": "error", "code": resp.status_code})
        except Exception as e:
            results.append({"instance_id": instance_id, "status": "error", "error": str(e)})
            logger.exception("Failed to push agent to instance %s", instance_id)

    return {"results": results}


@router.post("/{agent_id}/spawn")
async def spawn_subagent(
    agent_id: str,
    body: dict = Body(...),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Spawn an isolated subprocess agent for parallel work."""
    agent = await db.get(Agent, agent_id)
    if not agent or agent.org_id != org_id:
        raise HTTPException(404)

    task_prompt = body.get("prompt", "")
    if not task_prompt:
        raise HTTPException(400, "prompt is required")

    timeout = body.get("timeout", 120.0)
    from aios.core.subagent import subagent_pool
    result = await subagent_pool.spawn(
        agent_config={
            "id": agent.id,
            "name": agent.name,
            "llm_config": agent.llm_config,
            "system_prompt": agent.system_prompt,
            "tools": agent.tools or [],
            "governance_config": agent.governance_config or {},
            "org_id": agent.org_id,
        },
        task_prompt=task_prompt,
        timeout=timeout,
    )
    return {
        "task_id": result.task_id,
        "status": result.status,
        "output": result.output,
        "error": result.error,
        "duration_ms": result.duration_ms,
    }
