from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select

from aios.api.deps import get_current_user, get_org_id
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Agent, Conversation, Message, Organization, Team, User

router = APIRouter(prefix="/api/org", tags=["gdpr"])


@router.delete("")
async def delete_org(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    if user.role not in ("org_admin", "superadmin"):
        raise HTTPException(403)
    org = await db.get(Organization, org_id)
    if not org or org.slug in ("pixor", "default"):
        raise HTTPException(400, detail="org protegida")
    await db.execute(delete(Message).where(Message.org_id == org_id))
    await db.execute(delete(Conversation).where(Conversation.org_id == org_id))
    await db.execute(delete(Agent).where(Agent.org_id == org_id))
    await db.execute(delete(Team).where(Team.org_id == org_id))
    await db.execute(delete(User).where(User.org_id == org_id))
    await db.delete(org)
    await db.commit()
    return {"ok": True, "deleted": org_id}


@router.get("/export")
async def export_org(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    org = await db.get(Organization, org_id)
    agents = (
        (await db.execute(select(Agent).where(Agent.org_id == org_id))).scalars().all()
    )
    return {
        "org": {"id": org.id, "name": org.name, "slug": org.slug},
        "agents": [{"id": a.id, "name": a.name} for a in agents],
    }
