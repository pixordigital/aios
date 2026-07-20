import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aios.core.agent import AgentRuntime
from aios.core.limits import check_org_limits, track_usage
from aios.core.orchestrator import TeamOrchestrator
from aios.db.engine import get_db
from aios.db.models import Agent, Conversation, Message, Team
from aios.schemas import ConversationCreate, ConversationOut, MessageOut, MessageSend, SendMessageResponse
from .deps import get_current_user, get_org_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.post("", response_model=ConversationOut)
async def create_conversation(
    body: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    conv = Conversation(
        org_id=org_id,
        channel=body.channel or "web",
        agent_id=body.agent_id or None,
        team_id=body.team_id or None,
        external_id=body.external_id or None,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    channel: str | None = None,
    agent_id: str | None = None,
    team_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    query = select(Conversation).where(Conversation.org_id == org_id)
    if channel:
        query = query.where(Conversation.channel == channel)
    if agent_id:
        query = query.where(Conversation.agent_id == agent_id)
    if team_id:
        query = query.where(Conversation.team_id == team_id)
    query = query.order_by(Conversation.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.org_id != org_id:
        raise HTTPException(404)
    return conv


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(
    conversation_id: str,
    limit: int = Query(50, le=200),
    before: str | None = None,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.org_id != org_id:
        raise HTTPException(404)

    query = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    if before:
        query = query.where(Message.id < before)
    result = await db.execute(query)
    return list(reversed(result.scalars().all()))


@router.post("/{conversation_id}/messages", response_model=SendMessageResponse)
async def send_message(
    conversation_id: str,
    body: MessageSend,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.org_id != org_id:
        raise HTTPException(404)

    msg = Message(
        conversation_id=conversation_id,
        role="user",
        content=body.content,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    # check org limits before routing
    allowed, reason = await check_org_limits(org_id, db)
    if not allowed:
        reply_msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=f"⚠️ {reason}",
        )
        db.add(reply_msg)
        await db.commit()
        await db.refresh(reply_msg)
        return SendMessageResponse(user_message=msg, reply=reply_msg)

    # route to agent or team if assigned
    reply_msg: Message | None = None
    try:
        if conv.team_id:
            team = await db.get(Team, conv.team_id)
            if team and team.agents:
                orchestrator = TeamOrchestrator(team, list(team.agents))
                reply = await orchestrator.handle_message(conversation_id, body.content, db)
                if reply:
                    reply_msg = Message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=reply,
                    )
                    db.add(reply_msg)
                    await db.commit()
                    await db.refresh(reply_msg)
                    await track_usage(org_id, db, messages=1, tokens=len(reply))
        elif conv.agent_id:
            agent_model = await db.get(Agent, conv.agent_id)
            if agent_model:
                runtime = AgentRuntime(agent_model)
                reply = await runtime.run(conversation_id, body.content, db)
                if reply:
                    reply_msg = Message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=reply,
                    )
                    db.add(reply_msg)
                    await db.commit()
                    await db.refresh(reply_msg)
                    await track_usage(org_id, db, messages=1, tokens=len(reply))
    except Exception:
        logger.exception("Agent/team routing failed for conversation %s", conversation_id)

    return SendMessageResponse(user_message=msg, reply=reply_msg)
