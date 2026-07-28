from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select

from aios.channels.manager import manager as channel_mgr
from aios.core.audit import log_audit
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import ChannelConnection
from aios.schemas import ChannelCreate, ChannelOut, ChannelUpdate
from .deps import get_current_user, get_org_id

router = APIRouter(prefix="/api/channels", tags=["channels"])


@router.post("", response_model=ChannelOut)
async def create_channel(
    body: ChannelCreate,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    channel = ChannelConnection(
        org_id=org_id,
        channel_type=body.channel_type,
        label=body.label,
        config=body.config,
        agent_id=body.agent_id,
        team_id=body.team_id,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    await log_audit(db, org_id, "channel.create", "channel", user_id=user.id, resource_id=channel.id, details={"label": channel.label, "type": channel.channel_type})
    return channel


@router.get("", response_model=list[ChannelOut])
async def list_channels(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    result = await db.execute(
        select(ChannelConnection)
        .where(ChannelConnection.org_id == org_id)
        .order_by(ChannelConnection.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


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
    return {"is_active": channel.is_active}


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
    return {"ok": True}


@router.post("/test")
async def test_channel(body: dict = Body(...)):
    """Test connection without saving channel. Body: {channel_type, config}"""
    channel_type = body.get("channel_type", "")
    config = body.get("config", {})
    from aios.db.models import ChannelConnection as DummyConn
    dummy = DummyConn(channel_type=channel_type, config=config, org_id="test", label="test")
    try:
        ch = channel_mgr.build(dummy)
        result = await ch.test()
        return result
    except Exception as e:
        logger.exception("Channel test failed")
        return {"ok": False, "message": str(e)}


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
