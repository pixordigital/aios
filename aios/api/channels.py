from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aios.db.engine import get_db
from aios.db.models import ChannelConnection
from aios.schemas import ChannelCreate, ChannelOut
from .deps import get_org_id

router = APIRouter(prefix="/api/channels", tags=["channels"])


@router.post("", response_model=ChannelOut)
async def create_channel(
    body: ChannelCreate,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
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
    return channel


@router.get("", response_model=list[ChannelOut])
async def list_channels(
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    result = await db.execute(
        select(ChannelConnection)
        .where(ChannelConnection.org_id == org_id)
        .order_by(ChannelConnection.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{channel_id}", response_model=ChannelOut)
async def get_channel(
    channel_id: str,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    channel = await db.get(ChannelConnection, channel_id)
    if not channel or channel.org_id != org_id:
        raise HTTPException(404)
    return channel


@router.delete("/{channel_id}")
async def delete_channel(
    channel_id: str,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    channel = await db.get(ChannelConnection, channel_id)
    if not channel or channel.org_id != org_id:
        raise HTTPException(404)
    await db.delete(channel)
    await db.commit()
    return {"ok": True}


@router.post("/{channel_id}/start")
async def start_channel(
    channel_id: str,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    channel = await db.get(ChannelConnection, channel_id)
    if not channel or channel.org_id != org_id:
        raise HTTPException(404)
    channel.is_active = True
    await db.commit()
    return {"ok": True}


@router.post("/{channel_id}/stop")
async def stop_channel(
    channel_id: str,
    db: AsyncSession = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    channel = await db.get(ChannelConnection, channel_id)
    if not channel or channel.org_id != org_id:
        raise HTTPException(404)
    channel.is_active = False
    await db.commit()
    return {"ok": True}
