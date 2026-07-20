"""Remote admin API — for managing client instances from master server."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import func, select

from aios.config import settings
from aios.db.engine import async_session
from aios.db.models import Agent, Organization, User
from aios.api.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# ponytail: hardcoded master key. Replace with JWT-based master auth later.
MASTER_KEY = "pixor-master-key-change-me"


@router.post("/register-remote")
async def register_remote_admin(
    key: str = Body(...),
    org_name: str = Body(...),
):
    """Register this instance so master server can admin it.
    Called by deploy script during client setup.
    """
    if key != MASTER_KEY:
        raise HTTPException(403, "Invalid master key")

    async with async_session() as db:
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
    async with async_session() as db:
        org_count = (await db.execute(select(func.count(Organization.id)))).scalar() or 0
        agent_count = (await db.execute(select(func.count(Agent.id)))).scalar() or 0
    return {
        "version": "0.1.0",
        "orgs": org_count,
        "agents": agent_count,
        "healthy": True,
    }
