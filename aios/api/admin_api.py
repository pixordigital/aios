"""Remote admin API — for managing client instances from master server."""

import hmac
import logging

from fastapi import APIRouter, HTTPException, Body
from sqlalchemy import func, select

from aios.config import settings
from aios.db.backend import db_session
from aios.db.models import Agent, Organization

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


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
async def remote_health():
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
async def get_dlq(limit: int = 50):
    """Get dead letter queue entries (failed webhook messages)."""
    from aios.core.retry import get_dlq
    return {"entries": get_dlq(limit), "count": len(get_dlq())}


@router.post("/dlq/clear")
async def clear_dlq():
    """Clear dead letter queue."""
    from aios.core.retry import clear_dlq
    clear_dlq()
    return {"status": "ok"}
