"""Remote admin API — for managing client instances from master server."""

import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Body
from sqlalchemy import func, select

from aios.config import settings
from aios.db.backend import db_session
from aios.db.models import Agent, Organization

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def require_admin_key(authorization: str = Header(None)):
    """Require admin master key as Bearer token (used by fleet master server)."""
    expected = settings.admin_master_key
    if not expected:
        raise HTTPException(403, "Admin master key not configured on server")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(403, "Missing admin key")
    if not hmac.compare_digest(authorization[7:], expected):
        raise HTTPException(403, "Invalid admin key")


@router.post("/register-remote")
async def register_remote_admin(
    key: str = Body(...),
    org_name: str = Body(...),
):
    """Register this instance so master server can admin it."""
    expected = settings.admin_master_key
    if not expected:
        raise HTTPException(403, "Admin master key not configured on server")
    if not hmac.compare_digest(key, expected):
        raise HTTPException(403, "Invalid master key")

    async with db_session() as db:
        org = (await db.execute(
            select(Organization).where(Organization.slug == org_name.lower().replace(" ", "-"))
        )).scalar_one_or_none()
        if org:
            org.extra_data["remote_admin"] = True
            await db.commit()
            return {"status": "ok", "org_id": org.id}

    return {"status": "error", "message": "Org not found"}


@router.get("/health")
async def remote_health(_: None = Depends(require_admin_key)):
    """Health check for master monitoring."""
    async with db_session() as db:
        org_count = (await db.execute(select(func.count(Organization.id)))).scalar() or 0
        agent_count = (await db.execute(select(func.count(Agent.id)))).scalar() or 0
    return {
        "version": "0.1.0",
        "orgs": org_count,
        "agents": agent_count,
        "healthy": True,
    }


@router.get("/dlq")
async def get_dlq(limit: int = 50, _: None = Depends(require_admin_key)):
    """Get dead letter queue entries (failed messages)."""
    from aios.core.dead_letter import list_dlq
    entries = await list_dlq(limit)
    return {"entries": entries, "count": len(entries)}


@router.post("/dlq/clear")
async def clear_dlq(_: None = Depends(require_admin_key)):
    """Clear dead letter queue."""
    from aios.core.dead_letter import clear_dlq
    n = await clear_dlq()
    return {"status": "ok", "cleared": n}


@router.post("/dlq/{entry_id}/retry")
async def retry_dlq_endpoint(entry_id: str, _: None = Depends(require_admin_key)):
    """Re-enqueue a dead-lettered message for processing."""
    from aios.core.dead_letter import retry_dlq
    result = await retry_dlq(entry_id)
    if not result["ok"]:
        raise HTTPException(404, "DLQ entry not found")
    return {"status": "ok"}


@router.get("/health/agents")
async def agent_health_status(_: None = Depends(require_admin_key)):
    """Get health status of all agents."""
    from aios.core.agent_health import health_tracker
    return health_tracker.all_status()


@router.post("/health/agents/{agent_id}/reset")
async def reset_agent_health(agent_id: str, _: None = Depends(require_admin_key)):
    """Reset agent health status to healthy."""
    from aios.core.agent_health import health_tracker
    health_tracker.reset(agent_id)
    return {"status": "ok", "agent_id": agent_id}


@router.post("/fleet/refresh")
async def fleet_health_refresh(key: str = Body(...)):
    """Refresh health status of all remote fleet instances."""
    expected = settings.admin_master_key
    if not expected or not hmac.compare_digest(key, expected):
        raise HTTPException(403, "Invalid master key")
    from aios.db.models import RemoteInstance
    import httpx

    results = []
    async with db_session() as db:
        instances = (await db.execute(
            select(RemoteInstance).where(RemoteInstance.is_active == True)
        )).scalars().all()

        for inst in instances:
            try:
                headers = {}
                if inst.api_key:
                    headers["Authorization"] = f"Bearer {inst.api_key}"
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(f"{inst.base_url}/api/admin/health", headers=headers)
                    if resp.status_code == 200:
                        inst.extra_data["health"] = resp.json()
                        inst.extra_data["last_check"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
                        inst.is_active = True
                        results.append({"instance_id": inst.id, "name": inst.name, "status": "healthy"})
                    else:
                        inst.is_active = False
                        results.append({"instance_id": inst.id, "name": inst.name, "status": "unreachable"})
            except Exception as e:
                inst.is_active = False
                results.append({"instance_id": inst.id, "name": inst.name, "status": "error", "error": str(e)})

        await db.commit()

    return {"instances": results}
