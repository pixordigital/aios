"""Threads API — thread concept aliases for conversations.

Threads are conversations renamed for user-facing API clarity.
Backed by the same conversations table.
"""

from fastapi import APIRouter, Depends, HTTPException

from aios.api.deps import get_current_user
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Conversation, User
from sqlalchemy import select

router = APIRouter(prefix="/api/threads", tags=["threads"])


@router.get("")
async def list_threads(
    db: DatabaseBackend = Depends(get_db_backend),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation).where(Conversation.org_id == user.org_id).order_by(Conversation.created_at.desc()).limit(100)
    )
    threads = result.scalars().all()
    return {
        "threads": [
            {
                "id": t.id,
                "name": (t.extra_data or {}).get("thread_name") or t.external_id or t.id[:8],
                "channel": t.channel,
                "agent_id": t.agent_id,
                "created_at": str(t.created_at) if t.created_at else "",
                "message_count": len(t.messages),
            }
            for t in threads
        ]
    }


@router.get("/{thread_id}")
async def get_thread(
    thread_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    user: User = Depends(get_current_user),
):
    thread = await db.get(Conversation, thread_id)
    if not thread or thread.org_id != user.org_id:
        raise HTTPException(404, "Thread not found")
    messages = [
        {"id": m.id, "role": m.role, "content": m.content[:500], "created_at": str(m.created_at) if m.created_at else ""}
        for m in thread.messages
    ]
    return {
        "id": thread.id,
        "name": (thread.extra_data or {}).get("thread_name") or thread.external_id or thread.id[:8],
        "channel": thread.channel,
        "messages": messages,
    }
