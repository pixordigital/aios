from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aios.db.engine import get_db
from aios.db.models import Agent, Conversation, Message
from aios.schemas import BaseModel
from .deps import get_org_id

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


class OverviewOut(BaseModel):
    total_agents: int
    active_agents: int
    total_conversations: int
    total_messages: int


@router.get("/overview", response_model=OverviewOut)
async def overview(
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    agent_count = await db.execute(
        select(func.count(Agent.id)).where(Agent.org_id == org_id)
    )
    active_count = await db.execute(
        select(func.count(Agent.id)).where(
            Agent.org_id == org_id, Agent.status == "active"
        )
    )
    conv_count = await db.execute(
        select(func.count(Conversation.id)).where(Conversation.org_id == org_id)
    )
    msg_count = await db.execute(select(func.count(Message.id)))
    return OverviewOut(
        total_agents=agent_count.scalar() or 0,
        active_agents=active_count.scalar() or 0,
        total_conversations=conv_count.scalar() or 0,
        total_messages=msg_count.scalar() or 0,
    )
