import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from aios.core.agent import AgentRuntime
from aios.core.limits import check_org_limits, track_usage
from aios.core.orchestrator import TeamOrchestrator
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Agent, Conversation, Message, Team
from aios.schemas import ConversationCreate, ConversationOut, MessageOut, MessageSend, SendMessageResponse, PageResponse
from .deps import get_current_user, get_org_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.post("", response_model=ConversationOut)
async def create_conversation(
    body: ConversationCreate,
    db: DatabaseBackend = Depends(get_db_backend),
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


@router.get("", response_model=PageResponse[ConversationOut])
async def list_conversations(
    channel: str | None = None,
    agent_id: str | None = None,
    team_id: str | None = None,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    query = select(Conversation).where(Conversation.org_id == org_id)
    if channel:
        query = query.where(Conversation.channel == channel)
    if agent_id:
        query = query.where(Conversation.agent_id == agent_id)
    if team_id:
        query = query.where(Conversation.team_id == team_id)
    items = (await db.execute(query.order_by(Conversation.created_at.desc()).limit(limit + 1).offset(offset))).scalars().all()
    has_more = len(items) > limit
    if has_more:
        items = items[:limit]
    next_cursor = str(offset + limit) if has_more else None
    total = (await db.execute(
        select(__import__('sqlalchemy').func.count(Conversation.id)).where(Conversation.org_id == org_id)
    )).scalar()
    return PageResponse(items=items, next_cursor=next_cursor, has_more=has_more, total=total)


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.org_id != org_id:
        raise HTTPException(404)
    return conv


@router.get("/search/semantic")
async def semantic_search(q: str = "", top_k: int = 10, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    if not q:
        return {"results": []}
    from sqlalchemy import select as _sel
    from aios.db.models import Conversation, Message
    from aios.core.memory import _embed
    try:
        qvec = _embed(q)
    except Exception:
        qvec = None
    convs = (await db.execute(_sel(Conversation).where(Conversation.org_id == org_id).order_by(Conversation.created_at.desc()).limit(30))).scalars().all()
    scored = []
    for c in convs:
        # last message content
        last = (await db.execute(_sel(Message).where(Message.conversation_id == c.id).order_by(Message.created_at.desc()).limit(1))).scalars().first()
        text = (last.content if last else "") + " " + (c.external_id or "") + " " + c.channel
        if qvec:
            try:
                tvec = _embed(text[:500])
                dot = sum(a*b for a,b in zip(qvec, tvec))
                scored.append((dot, c))
            except Exception:
                if q.lower() in text.lower():
                    scored.append((0.5, c))
        else:
            if q.lower() in text.lower():
                scored.append((1, c))
    scored.sort(key=lambda x: -x[0])
    return {"results": [{"id": c.id, "channel": c.channel, "external_id": c.external_id, "score": round(s,3)} for s,_ in scored[:top_k]]}

@router.get("/{conversation_id}/handover")
async def get_handover(conversation_id: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.org_id != org_id:
        raise HTTPException(404)
    h = (conv.extra_data or {}).get("handover", {"status": "bot"})
    pending = []
    try:
        from sqlalchemy import select as _sel

        from aios.db.models import PendingAction

        pending = (await db.execute(_sel(PendingAction).where(PendingAction.conversation_id == conversation_id, PendingAction.status == "pending"))).scalars().all()
        pending = [{"id": p.id, "tool_name": p.tool_name, "tool_args": p.tool_args, "context_summary": p.context_summary} for p in pending]
    except Exception:
        pass
    return {"handover": h, "pending": pending}


@router.post("/{conversation_id}/handover")
async def post_handover(conversation_id: str, body: dict, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.org_id != org_id:
        raise HTTPException(404)
    action = body.get("action", "take")
    extra = dict(conv.extra_data or {})
    h = dict(extra.get("handover", {}))
    if action == "take":
        h.update({"status": "human", "human_id": user.id, "at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()})
    else:
        h.update({"status": "bot", "human_id": None, "at": None})
    extra["handover"] = h
    conv.extra_data = extra
    await db.commit()
    return {"handover": h}


@router.post("/{conversation_id}/human-reply")
async def human_reply(conversation_id: str, body: dict, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.org_id != org_id:
        raise HTTPException(404)
    text = (body.get("content") or body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "content required")
    msg = Message(conversation_id=conversation_id, role="assistant", content=text, org_id=org_id, extra_data={"human": True, "human_id": user.id})
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    # deliver via channel if exists
    try:
        from aios.core.dispatch import dispatch_outbound

        await dispatch_outbound(conv, text)
    except Exception:
        pass
    return msg


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(
    conversation_id: str,
    limit: int = Query(50, le=200),
    before: str | None = None,
    db: DatabaseBackend = Depends(get_db_backend),
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
    db: DatabaseBackend = Depends(get_db_backend),
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
        org_id=org_id,
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
            org_id=org_id,
        )
        db.add(reply_msg)
        await db.commit()
        await db.refresh(reply_msg)
        return SendMessageResponse(user_message=msg, reply=reply_msg)

    if (conv.extra_data or {}).get("handover", {}).get("status") == "human":
        return SendMessageResponse(user_message=msg, reply=None)

    # route to agent or team if assigned, with retry + failover
    reply_msg: Message | None = None
    try:
        from aios.core.agent_health import health_tracker
        if conv.team_id:
            team = await db.get(Team, conv.team_id)
            if team and team.agents:
                available = [a for a in team.agents if health_tracker.is_available(a.id)]
                if available:
                    orchestrator = TeamOrchestrator(team, available)
                    reply = await orchestrator.handle_message(conversation_id, body.content, db)
                    if reply:
                        reply_msg = Message(
                            conversation_id=conversation_id,
                            role="assistant",
                            content=reply,
                            org_id=org_id,
                        )
                        db.add(reply_msg)
                        await db.commit()
                        await db.refresh(reply_msg)
                        tokens = getattr(runtime, "_last_tokens", len(reply)) if 'runtime' in locals() else len(reply)
                        await track_usage(org_id, db, messages=1, tokens=tokens, llm_calls=1)
                    elif len(available) > 1:
                        # team failed, try each agent individually
                        for agent in available:
                            try:
                                runtime = AgentRuntime(agent)
                                reply = await runtime.run(conversation_id, body.content, db)
                                if reply:
                                    reply_msg = Message(
                                        conversation_id=conversation_id,
                                        role="assistant",
                                        content=reply,
                                        org_id=org_id,
                                    )
                                    db.add(reply_msg)
                                    await db.commit()
                                    await db.refresh(reply_msg)
                                    await track_usage(org_id, db, messages=1, tokens=getattr(runtime, "_last_tokens", len(reply)), llm_calls=1)
                                    break
                            except Exception:
                                logger.exception("Failover: agent %s failed", agent.id)
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
                        org_id=org_id,
                    )
                    db.add(reply_msg)
                    await db.commit()
                    await db.refresh(reply_msg)
                    await track_usage(org_id, db, messages=1, tokens=getattr(runtime, "_last_tokens", len(reply)), llm_calls=1)
    except Exception:
        logger.exception("Agent/team routing failed for conversation %s", conversation_id)

    return SendMessageResponse(user_message=msg, reply=reply_msg)


@router.post("/{conversation_id}/messages/stream")
async def send_message_stream(
    conversation_id: str,
    body: MessageSend,
    request: Request,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """SSE streaming endpoint. Yields token/tool_call/done events as JSON."""
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.org_id != org_id:
        raise HTTPException(404)

    msg = Message(conversation_id=conversation_id, role="user", content=body.content, org_id=org_id, extra_data={"handover": (conv.extra_data or {}).get("handover")})
    db.add(msg)
    await db.commit()

    if (conv.extra_data or {}).get("handover", {}).get("status") == "human":
        async def handover_stream():
            yield f"data: {json.dumps({'type': 'token', 'content': '👤 Atendimento humano ativo — agente pausado'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(handover_stream(), media_type="text/event-stream")

    allowed, reason = await check_org_limits(org_id, db)
    if not allowed:
        async def err_stream():
            yield f"data: {json.dumps({'type': 'token', 'content': f'⚠️ {reason}'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(err_stream(), media_type="text/event-stream")

    async def event_stream():
        try:
            if conv.team_id:
                team = await db.get(Team, conv.team_id)
                if team and team.agents:
                    orch = TeamOrchestrator(team, list(team.agents))
                    toks = 0
                    async for ev in orch.handle_message_stream(conversation_id, body.content, db):
                        if ev.get("tokens"):
                            toks = ev["tokens"]
                        yield f"data: {json.dumps(ev)}\n\n"
                        if ev["type"] == "done":
                            break
                    await track_usage(org_id, db, messages=1, tokens=toks, llm_calls=1)
                    return
            elif conv.agent_id:
                agent_model = await db.get(Agent, conv.agent_id)
                if agent_model:
                    runtime = AgentRuntime(agent_model)
                    toks = 0
                    async for ev in runtime.run_stream(conversation_id, body.content, db):
                        if ev.get("tokens"):
                            toks = ev["tokens"]
                        yield f"data: {json.dumps(ev)}\n\n"
                        if ev["type"] == "done":
                            break
                    await track_usage(org_id, db, messages=1, tokens=toks, llm_calls=1)
                    return
        except Exception:
            logger.exception("Stream failed for conversation %s", conversation_id)
            yield f"data: {json.dumps({'type': 'error', 'error': 'Agent error'})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
