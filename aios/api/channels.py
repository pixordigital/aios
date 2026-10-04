import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select, func

logger = logging.getLogger(__name__)

from aios.channels.evolution import EvolutionChannel
from aios.channels.manager import manager as channel_mgr
from aios.core.audit import log_audit
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import ChannelConnection, Conversation, Message
from aios.schemas import ChannelCreate, ChannelOut, ChannelUpdate, PageResponse
from .deps import get_current_user, get_org_id

router = APIRouter(prefix="/api/channels", tags=["channels"])


@router.post("", response_model=ChannelOut)
async def create_channel(
    body: ChannelCreate,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    from aios.db.models import Agent, Team

    # A channel bound to another org's agent/team would let this org spend
    # their budget and read their runs. Verify ownership on both ids.
    if body.agent_id:
        ag = await db.get(Agent, body.agent_id)
        if not ag or ag.org_id != org_id:
            raise HTTPException(400, "agent_id inválido")
    if body.team_id:
        t = await db.get(Team, body.team_id)
        if not t or t.org_id != org_id:
            raise HTTPException(400, "team_id inválido")
    # config carries the provider credentials (bot tokens, API keys). It was
    # persisted verbatim, so a Slack bot token POSTed here sat in cleartext in
    # the DB while every other path encrypted it.
    from aios.core.secrets import encrypt_channel_config

    channel = ChannelConnection(
        org_id=org_id,
        channel_type=body.channel_type,
        label=body.label,
        config=encrypt_channel_config(body.config or {}),
        agent_id=body.agent_id,
        team_id=body.team_id,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    await log_audit(db, org_id, "channel.create", "channel", user_id=user.id, resource_id=channel.id, details={"label": channel.label, "type": channel.channel_type})
    return channel


@router.get("", response_model=PageResponse[ChannelOut])
async def list_channels(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    items = (await db.execute(
        select(ChannelConnection)
        .where(ChannelConnection.org_id == org_id)
        .order_by(ChannelConnection.created_at.desc())
        .limit(limit + 1)
        .offset(offset)
    )).scalars().all()
    has_more = len(items) > limit
    if has_more:
        items = items[:limit]
    next_cursor = str(offset + limit) if has_more else None
    total = (await db.execute(
        select(__import__('sqlalchemy').func.count(ChannelConnection.id)).where(ChannelConnection.org_id == org_id)
    )).scalar()
    return PageResponse(items=items, next_cursor=next_cursor, has_more=has_more, total=total)


@router.get("/{channel_id}", response_model=ChannelOut)
async def get_channel(
    channel_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    channel = await db.get(ChannelConnection, channel_id)
    if not channel or channel.org_id != org_id:
        raise HTTPException(404)
    return channel


@router.delete("/{channel_id}")
async def delete_channel(
    channel_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    channel = await db.get(ChannelConnection, channel_id)
    if not channel or channel.org_id != org_id:
        raise HTTPException(404)
    await log_audit(db, org_id, "channel.delete", "channel", user_id=user.id, resource_id=channel_id, details={"label": channel.label})
    await db.delete(channel)
    await db.commit()
    return {"ok": True}


@router.put("/{channel_id}", response_model=ChannelOut)
async def update_channel(
    channel_id: str,
    body: ChannelUpdate,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    channel = await db.get(ChannelConnection, channel_id)
    if not channel or channel.org_id != org_id:
        raise HTTPException(404)
    update_data = body.model_dump(exclude_unset=True)
    for key, val in update_data.items():
        if key == "config" and val:
            from aios.core.secrets import encrypt_channel_config

            val = encrypt_channel_config(val)
        setattr(channel, key, val)
    await db.commit()
    await db.refresh(channel)
    return channel


@router.post("/{channel_id}/toggle")
async def toggle_channel(
    channel_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    channel = await db.get(ChannelConnection, channel_id)
    if not channel or channel.org_id != org_id:
        raise HTTPException(404)
    channel.is_active = not channel.is_active
    await db.commit()
    # Start/stop the live adapter. Flipping the flag alone left the poller
    # running (or never started), so a disabled email channel kept replying and
    # a newly enabled one received nothing until the next restart.
    await _sync_channel(channel, channel.is_active, db)
    return {"is_active": channel.is_active}


async def _sync_channel(channel: ChannelConnection, is_active: bool, db) -> bool:
    """Bring a connection's live adapter in line with its DB flag.

    `main.py` starts channels once during lifespan; that is the only place
    `channel_mgr.start()` was ever called, so anything created or toggled
    afterwards never got a running adapter. Never raises — a failed start must
    not fail the API call that toggled the flag.
    """
    try:
        from sqlalchemy.orm import selectinload

        from aios.db.models import Agent, Team

        agent_or_team = None
        if channel.agent_id:
            agent_or_team = await db.get(Agent, channel.agent_id)
        elif channel.team_id:
            agent_or_team = await db.get(
                Team, channel.team_id, options=[selectinload(Team.agents)]
            )
        return await channel_mgr.sync(channel, is_active, agent_or_team, db)
    except Exception:
        logger.exception("channel sync failed for %s", getattr(channel, "id", "?"))
        return False


@router.post("/{channel_id}/start")
async def start_channel(
    channel_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    channel = await db.get(ChannelConnection, channel_id)
    if not channel or channel.org_id != org_id:
        raise HTTPException(404)
    channel.is_active = True
    await db.commit()
    started = await _sync_channel(channel, True, db)
    return {"ok": True, "running": started}


@router.post("/test")
async def test_channel(body: dict = Body(...), user=Depends(get_current_user)):
    """Test connection without saving channel. Body: {channel_type, config}"""
    channel_type = body.get("channel_type", "")
    config = body.get("config", {})

    # SSRF guard: reject private/internal URLs in channel config
    from urllib.parse import urlparse
    from aios.tools.http_get import _is_private
    for key in ("server_url", "imap_server", "smtp_server"):
        url = config.get(key, "")
        if not url:
            continue
        if not url.startswith(("http://", "https://")):
            url = "https://" + url  # normalize for hostname extraction
        host = urlparse(url).hostname
        if not host or _is_private(host):
            logger.warning("Channel test blocked: private URL for %s (%s)", key, host)
            return {"ok": False, "message": f"{key} must be a public URL"}

    from aios.db.models import ChannelConnection as DummyConn
    dummy = DummyConn(channel_type=channel_type, config=config, org_id="test", label="test")
    try:
        ch = channel_mgr.build(dummy)
        result = await ch.test()
        return result
    except Exception:
        # The raw text can embed URLs, tokens or credentials from the user's own
        # config, so it goes to the server log only. The caller gets a generic
        # failure rather than a reflection of their secrets.
        logger.exception("Channel test failed")
        return {"ok": False, "message": "teste de canal falhou; veja o log do servidor"}


@router.post("/evolution/create-instance")
async def create_evolution_instance(
    body: dict = Body(...),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Create new Evolution instance (Baileys or Meta Cloud API).
    Body: {instance_name, provider: "baileys"|"meta", channel_id}
    """
    instance_name = body.get("instance_name", "")
    provider = body.get("provider", "baileys")
    channel_id = body.get("channel_id", "")

    if not instance_name:
        return {"ok": False, "message": "instance_name required"}

    # Get the Evolution channel to use for provisioning
    if not channel_id:
        return {"ok": False, "message": "channel_id required"}

    channel = await db.get(ChannelConnection, channel_id)
    if not channel or channel.org_id != org_id or channel.channel_type != "evolution":
        return {"ok": False, "message": "Invalid Evolution channel"}

    # Instance names are resolved globally by the inbound webhook (it has no org
    # context until it finds the channel), and a collision resolves to the
    # lowest id — so two orgs sharing a name silently deliver one tenant's
    # messages to the other's agent. Refuse the collision at creation, when it
    # is still cheap to pick another name.
    from sqlalchemy import select

    from aios.db.models import ChannelConnection as _CC

    clash = (
        await db.execute(
            select(_CC.id, _CC.org_id).where(
                _CC.channel_type == "evolution",
                _CC.id != channel_id,
                _CC.config["instance"].as_string() == instance_name,
            ).limit(1)
        )
    ).first()
    if clash:
        _clash_id, _clash_org = clash
        if _clash_org == org_id:
            return {"ok": False, "message": f"instance name {instance_name!r} is already in use in this organization"}
        return {"ok": False, "message": f"instance name {instance_name!r} is already taken; pick another"}
    from aios.channels.manager import manager as channel_mgr
    ch = channel_mgr.build(channel, db=db)
    # channel_type == "evolution" was verified above; without narrowing, the
    # base Channel type hides the Evolution-only methods below.
    assert isinstance(ch, EvolutionChannel), f"expected EvolutionChannel for {channel.id}"
    result = await ch.create_instance(instance_name, provider)

    if result["ok"]:
        await log_audit(db, org_id, "evolution.instance.create", "channel", user_id=user.id, resource_id=channel_id, details={"instance": instance_name, "provider": provider})
        if not result.get("webhook_ok", True):
            # An instance with no inbound webhook is not provisioned. Say so
            # instead of returning ok and leaving the operator to find out
            # when a customer messages and nothing happens.
            result["message"] = (
                f"Instance created, but the webhook could not be set: "
                f"{result.get('webhook_error')}. Inbound messages will not arrive."
            )
            logger.error("create_evolution_instance: %s", result["message"])

    return result


@router.post("/evolution/delete-instance")
async def delete_evolution_instance(
    body: dict = Body(...),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Delete Evolution instance.
    Body: {instance_name, channel_id}
    """
    instance_name = body.get("instance_name", "")
    channel_id = body.get("channel_id", "")

    if not instance_name or not channel_id:
        return {"ok": False, "message": "instance_name and channel_id required"}

    channel = await db.get(ChannelConnection, channel_id)
    if not channel or channel.org_id != org_id or channel.channel_type != "evolution":
        return {"ok": False, "message": "Invalid Evolution channel"}

    from aios.channels.manager import manager as channel_mgr
    ch = channel_mgr.build(channel, db=db)
    # channel_type == "evolution" was verified above; without narrowing, the
    # base Channel type hides the Evolution-only methods below.
    assert isinstance(ch, EvolutionChannel), f"expected EvolutionChannel for {channel.id}"
    result = await ch.delete_instance(instance_name)

    if result["ok"]:
        await log_audit(db, org_id, "evolution.instance.delete", "channel", user_id=user.id, resource_id=channel_id, details={"instance": instance_name})

    return result


@router.get("/evolution/list-instances")
async def list_evolution_instances(
    channel_id: str = Query(...),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    """List all Evolution instances for a channel."""
    channel = await db.get(ChannelConnection, channel_id)
    if not channel or channel.org_id != org_id or channel.channel_type != "evolution":
        return {"ok": False, "message": "Invalid Evolution channel"}

    from aios.channels.manager import manager as channel_mgr
    ch = channel_mgr.build(channel, db=db)
    # channel_type == "evolution" was verified above; without narrowing, the
    # base Channel type hides the Evolution-only methods below.
    assert isinstance(ch, EvolutionChannel), f"expected EvolutionChannel for {channel.id}"
    return await ch.list_instances()


@router.get("/evolution/qrcode")
async def get_evolution_qrcode(
    channel_id: str = Query(...),
    instance_name: str = Query(...),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    """Get QR code for Baileys instance."""
    channel = await db.get(ChannelConnection, channel_id)
    if not channel or channel.org_id != org_id or channel.channel_type != "evolution":
        return {"ok": False, "message": "Invalid Evolution channel"}

    from aios.channels.manager import manager as channel_mgr
    ch = channel_mgr.build(channel, db=db)
    # channel_type == "evolution" was verified above; without narrowing, the
    # base Channel type hides the Evolution-only methods below.
    assert isinstance(ch, EvolutionChannel), f"expected EvolutionChannel for {channel.id}"
    return await ch.get_instance_qrcode(instance_name)


@router.post("/{channel_id}/stop")
async def stop_channel(
    channel_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    channel = await db.get(ChannelConnection, channel_id)
    if not channel or channel.org_id != org_id:
        raise HTTPException(404)
    channel.is_active = False
    await db.commit()
    return {"ok": True}


@router.get("/evolution/{instance_name}/analytics")
async def evolution_analytics(
    instance_name: str,
    days: int = Query(7, ge=1, le=90),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    """Get Evolution instance message analytics using channel_connection_id and separate db session."""
    
    # Find channel connection for this instance
    # Use JSON extraction compatible with both SQLite and PostgreSQL
    channel = (await db.execute(
        select(ChannelConnection).where(
            ChannelConnection.channel_type == "evolution",
            ChannelConnection.org_id == org_id,
            func.json_extract(ChannelConnection.config, '$.instance') == instance_name
        )
    )).scalar_one_or_none()
    
    if not channel:
        raise HTTPException(404, "Instance not found or not linked to this org")
    
    channel_connection_id = channel.id
    
    # Use separate db session for analytics query
    from aios.db.engine import async_session
    
    since = datetime.now(timezone.utc) - timedelta(days=days)
    
    async with async_session() as db2:
        # Get message stats per day
        daily_stats = await db2.execute(
            select(
                func.date(Conversation.created_at).label("day"),
                func.count(Message.id).label("total_messages"),
                func.count(Message.id).filter(Message.role == "user").label("inbound"),
                func.count(Message.id).filter(Message.role == "assistant").label("outbound"),
            )
            .select_from(Conversation)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(
                Conversation.channel_connection_id == channel_connection_id,
                Conversation.created_at >= since
            )
            .group_by(func.date(Conversation.created_at))
            .order_by(func.date(Conversation.created_at))
        )
        
        daily = [
            {
                "day": str(row.day),
                "total": row.total_messages,
                "inbound": row.inbound,
                "outbound": row.outbound,
            }
            for row in daily_stats
        ]
        
        # Total stats
        total_stats = await db2.execute(
            select(
                func.count(Message.id).label("total"),
                func.count(Message.id).filter(Message.role == "user").label("inbound"),
                func.count(Message.id).filter(Message.role == "assistant").label("outbound"),
            )
            .select_from(Conversation)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(
                Conversation.channel_connection_id == channel_connection_id,
                Conversation.created_at >= since
            )
        )
        total_row = total_stats.first()
        
        # Last activity
        last_msg = await db2.execute(
            select(Message.created_at)
            .select_from(Conversation)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(Conversation.channel_connection_id == channel_connection_id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        last_activity = last_msg.scalar_one_or_none()
    
    return {
        "instance_name": instance_name,
        "channel_connection_id": channel_connection_id,
        "period_days": days,
        "total_messages": total_row.total if total_row else 0,
        "inbound": total_row.inbound if total_row else 0,
        "outbound": total_row.outbound if total_row else 0,
        "daily": daily,
        "last_activity": str(last_activity) if last_activity else None,
    }
