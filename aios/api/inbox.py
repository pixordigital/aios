"""Unified Inbox API — multi-channel conversation view with human assignment."""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, or_, desc

from aios.core.audit import log_audit
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Conversation, Message, ChannelConnection, User, Team
from aios.schemas import PageResponse
from .deps import get_current_user, get_org_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


@router.get("", response_model=PageResponse[dict])
async def list_inbox_conversations(
    channel_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),  # open, closed, assigned, unassigned
    assigned_to_me: bool = Query(False),
    team_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """List conversations across all channels for unified inbox."""
    
    # Base query with conversation and latest message
    from sqlalchemy.orm import selectinload
    
    query = select(Conversation).where(Conversation.org_id == org_id)
    
    if channel_type:
        query = query.where(Conversation.channel == channel_type)
    
    if team_id:
        query = query.where(Conversation.team_id == team_id)
    
    if assigned_to_me:
        query = query.where(Conversation.extra_data["assigned_to"].astext == user.id)
    elif status == "assigned":
        query = query.where(Conversation.extra_data["assigned_to"].isnot(None))
    elif status == "unassigned":
        query = query.where(or_(
            Conversation.extra_data["assigned_to"].is_(None),
            Conversation.extra_data["assigned_to"] == ""
        ))
    elif status == "open":
        query = query.where(Conversation.extra_data["status"].astext != "closed")
    elif status == "closed":
        query = query.where(Conversation.extra_data["status"].astext == "closed")
    
    if search:
        search_term = f"%{search}%"
        query = query.where(or_(
            Conversation.external_id.ilike(search_term),
            Conversation.extra_data["contact_name"].astext.ilike(search_term),
        ))
    
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            query = query.where(Conversation.created_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            query = query.where(Conversation.created_at <= dt_to)
        except ValueError:
            pass
    
    # Order by last activity (most recent first)
    query = query.order_by(desc(Conversation.updated_at)).limit(limit + 1).offset(offset)
    
    result = await db.execute(query)
    conversations = result.scalars().all()
    
    has_more = len(conversations) > limit
    if has_more:
        conversations = conversations[:limit]
    
    next_cursor = str(offset + limit) if has_more else None
    
    # Get channel info for each conversation
    channel_ids = [c.channel_connection_id for c in conversations if c.channel_connection_id]
    channels = {}
    if channel_ids:
        channel_result = await db.execute(
            select(ChannelConnection).where(ChannelConnection.id.in_(channel_ids))
        )
        channels = {c.id: c for c in channel_result.scalars()}
    
    # Build response with last message preview
    items = []
    for conv in conversations:
        # Get last message
        last_msg_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(desc(Message.created_at))
            .limit(1)
        )
        last_msg = last_msg_result.scalar_one_or_none()
        
        # Get unread count (messages after last read)
        # For simplicity, count all messages for now
        unread_result = await db.execute(
            select(func.count(Message.id))
            .where(Message.conversation_id == conv.id, Message.role == "user")
        )
        unread_count = unread_result.scalar() or 0
        
        channel = channels.get(conv.channel_connection_id)
        
        assigned_to = conv.extra_data.get("assigned_to") if conv.extra_data else None
        assignee_name = None
        if assigned_to:
            assignee = await db.get(User, assigned_to)
            if assignee:
                assignee_name = assignee.email
        
        items.append({
            "id": conv.id,
            "channel": conv.channel,
            "channel_label": channel.label if channel else conv.channel,
            "external_id": conv.external_id,
            "contact_name": conv.extra_data.get("contact_name") if conv.extra_data else None,
            "contact_avatar": conv.extra_data.get("contact_avatar") if conv.extra_data else None,
            "status": conv.extra_data.get("status", "open") if conv.extra_data else "open",
            "assigned_to": assigned_to,
            "assignee_name": assignee_name,
            "team_id": conv.team_id,
            "last_message": last_msg.content[:100] if last_msg else None,
            "last_message_at": str(last_msg.created_at) if last_msg else str(conv.updated_at),
            "last_message_role": last_msg.role if last_msg else None,
            "unread_count": unread_count,
            "created_at": str(conv.created_at),
            "updated_at": str(conv.updated_at),
        })
    
    # Total count
    total_query = select(func.count(Conversation.id)).where(Conversation.org_id == org_id)
    total = (await db.execute(total_query)).scalar() or 0
    
    return PageResponse(
        items=items,
        next_cursor=next_cursor,
        has_more=has_more,
        total=total,
    )


@router.get("/{conversation_id}")
async def get_inbox_conversation(
    conversation_id: str,
    include_messages: bool = Query(True),
    message_limit: int = Query(100, ge=1, le=500),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Get full conversation with messages for inbox detail view."""
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.org_id != org_id:
        raise HTTPException(404)
    
    # Get channel info
    channel = None
    if conv.channel_connection_id:
        channel = await db.get(ChannelConnection, conv.channel_connection_id)
    
    # Get assignee
    assigned_to = conv.extra_data.get("assigned_to") if conv.extra_data else None
    assignee = None
    if assigned_to:
        assignee = await db.get(User, assigned_to)
    
    result = {
        "id": conv.id,
        "channel": conv.channel,
        "channel_label": channel.label if channel else conv.channel,
        "channel_connection_id": conv.channel_connection_id,
        "external_id": conv.external_id,
        "contact_name": conv.extra_data.get("contact_name") if conv.extra_data else None,
        "contact_phone": conv.extra_data.get("contact_phone") if conv.extra_data else None,
        "contact_email": conv.extra_data.get("contact_email") if conv.extra_data else None,
        "contact_avatar": conv.extra_data.get("contact_avatar") if conv.extra_data else None,
        "status": conv.extra_data.get("status", "open") if conv.extra_data else "open",
        "assigned_to": assigned_to,
        "assignee": assignee.email if assignee else None,
        "team_id": conv.team_id,
        "tags": conv.extra_data.get("tags", []) if conv.extra_data else [],
        "created_at": str(conv.created_at),
        "updated_at": str(conv.updated_at),
    }
    
    if include_messages:
        msg_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at)
            .limit(message_limit)
        )
        messages = msg_result.scalars().all()
        
        result["messages"] = [{
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "agent_id": m.agent_id,
            "channel_message_id": m.channel_message_id,
            "created_at": str(m.created_at),
        } for m in messages]
    
    return result


@router.post("/{conversation_id}/assign")
async def assign_conversation(
    conversation_id: str,
    assignee_id: str = Query(...),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Assign conversation to a team member."""
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.org_id != org_id:
        raise HTTPException(404)
    
    # Verify assignee is in same org
    assignee = await db.get(User, assignee_id)
    if not assignee or assignee.org_id != org_id:
        raise HTTPException(400, "Invalid assignee")
    
    extra = dict(conv.extra_data or {})
    extra["assigned_to"] = assignee_id
    extra["assigned_at"] = datetime.now(timezone.utc).isoformat()
    extra["assigned_by"] = user.id
    conv.extra_data = extra
    await db.commit()
    
    await log_audit(db, org_id, "inbox.assign", "conversation",
                   user_id=user.id, resource_id=conversation_id,
                   details={"assignee_id": assignee_id})
    
    return {"ok": True, "assigned_to": assignee_id, "assignee_name": assignee.email}


@router.post("/{conversation_id}/unassign")
async def unassign_conversation(
    conversation_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Unassign conversation."""
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.org_id != org_id:
        raise HTTPException(404)
    
    extra = dict(conv.extra_data or {})
    extra["assigned_to"] = None
    extra["assigned_at"] = None
    extra["assigned_by"] = None
    conv.extra_data = extra
    await db.commit()
    
    await log_audit(db, org_id, "inbox.unassign", "conversation",
                   user_id=user.id, resource_id=conversation_id)
    
    return {"ok": True}


@router.post("/{conversation_id}/close")
async def close_conversation(
    conversation_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Mark conversation as closed."""
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.org_id != org_id:
        raise HTTPException(404)
    
    extra = dict(conv.extra_data or {})
    extra["status"] = "closed"
    extra["closed_at"] = datetime.now(timezone.utc).isoformat()
    extra["closed_by"] = user.id
    conv.extra_data = extra
    await db.commit()
    
    await log_audit(db, org_id, "inbox.close", "conversation",
                   user_id=user.id, resource_id=conversation_id)
    
    return {"ok": True, "status": "closed"}


@router.post("/{conversation_id}/reopen")
async def reopen_conversation(
    conversation_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Reopen a closed conversation."""
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.org_id != org_id:
        raise HTTPException(404)
    
    extra = dict(conv.extra_data or {})
    extra["status"] = "open"
    extra["reopened_at"] = datetime.now(timezone.utc).isoformat()
    extra["reopened_by"] = user.id
    conv.extra_data = extra
    await db.commit()
    
    await log_audit(db, org_id, "inbox.reopen", "conversation",
                   user_id=user.id, resource_id=conversation_id)
    
    return {"ok": True, "status": "open"}


@router.post("/{conversation_id}/send")
async def send_inbox_message(
    conversation_id: str,
    content: str = Query(...),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Send a message from the inbox (human reply)."""
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.org_id != org_id:
        raise HTTPException(404)
    
    # Save human message
    msg = Message(
        conversation_id=conv.id,
        org_id=org_id,
        role="assistant",
        content=content,
        agent_id=None,  # Human agent
        extra_data={"from_inbox": True, "user_id": user.id},
    )
    db.add(msg)
    await db.commit()
    
    # Deliver via channel
    if conv.channel_connection_id:
        from aios.tasks.queue import enqueue_job
        await enqueue_job(
            "deliver_message",
            channel_connection_id=conv.channel_connection_id,
            conversation_id=conv.id,
            text=content,
            extra_data='{"from_inbox": true, "user_id": "' + user.id + '"}',
        )
    
    await log_audit(db, org_id, "inbox.send", "message",
                   user_id=user.id, resource_id=msg.id,
                   details={"conversation_id": conversation_id})
    
    return {"ok": True, "message_id": msg.id}


@router.get("/stats/summary")
async def inbox_stats(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Get inbox statistics summary."""
    # Total conversations
    total = (await db.execute(
        select(func.count(Conversation.id)).where(Conversation.org_id == org_id)
    )).scalar() or 0
    
    # Open conversations
    open_count = (await db.execute(
        select(func.count(Conversation.id))
        .where(Conversation.org_id == org_id, Conversation.extra_data["status"].astext != "closed")
    )).scalar() or 0
    
    # Assigned to me
    assigned_me = (await db.execute(
        select(func.count(Conversation.id))
        .where(Conversation.org_id == org_id, Conversation.extra_data["assigned_to"].astext == user.id)
    )).scalar() or 0
    
    # Unassigned
    unassigned = (await db.execute(
        select(func.count(Conversation.id))
        .where(Conversation.org_id == org_id, or_(
            Conversation.extra_data["assigned_to"].is_(None),
            Conversation.extra_data["assigned_to"] == ""
        ))
    )).scalar() or 0
    
    # By channel
    by_channel = await db.execute(
        select(Conversation.channel, func.count(Conversation.id))
        .where(Conversation.org_id == org_id)
        .group_by(Conversation.channel)
    )
    channel_stats = {row[0]: row[1] for row in by_channel}
    
    return {
        "total": total,
        "open": open_count,
        "assigned_to_me": assigned_me,
        "unassigned": unassigned,
        "by_channel": channel_stats,
    }