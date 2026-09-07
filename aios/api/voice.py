"""Voice API — TTS, chamadas outbound (SDR/support), webhook inbound."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from aios.config import settings
from aios.core.voice import place_call, synthesize, transcribe_audio
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Agent, ChannelConnection, Conversation, Message, Team

from .deps import get_current_user, get_org_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])


class SayRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    voice: str = ""
    channel_id: str = ""


class CallRequest(BaseModel):
    to: str = Field(min_length=7, max_length=30)
    script: str = Field(min_length=1, max_length=5000)
    agent_id: str = ""
    team_id: str = ""
    channel_id: str = ""


async def _channel_config(db: DatabaseBackend, org_id: str, channel_id: str) -> dict:
    if not channel_id:
        return {}
    ch = await db.get(ChannelConnection, channel_id)
    if not ch or ch.org_id != org_id or ch.channel_type != "voice":
        return {}
    try:
        from aios.core.secrets import decrypt_channel_config

        cfg = ch.config or {}
        if any(str(v).startswith("enc:") for v in cfg.values() if isinstance(v, str)):
            cfg = decrypt_channel_config(cfg)
        return cfg
    except Exception:
        return ch.config or {}


@router.get("/providers")
async def providers(user=Depends(get_current_user)):
    return {
        "providers": ["elevenlabs", "vapi", "retell", "selfhosted", "livekit"],
        "default": settings.voice_provider,
        "selfhosted": {"tts_url": settings.voice_tts_url, "stt_url": settings.voice_stt_url},
        "bridge_configured": bool(settings.voice_bridge_url),
    }


@router.post("/say")
async def say(
    body: SayRequest,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    cfg = await _channel_config(db, org_id, body.channel_id)
    res = await synthesize(body.text, cfg, body.voice)
    if not res.get("ok"):
        raise HTTPException(502, res.get("error", "tts falhou"))
    try:
        from aios.core.limits import track_usage

        await track_usage(org_id, db, messages=1, tokens=len(body.text) // 4, cost_usd=0.01)
    except Exception:
        pass
    return res


@router.post("/call")
async def call(
    body: CallRequest,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    if body.agent_id:
        ag = await db.get(Agent, body.agent_id)
        if not ag or ag.org_id != org_id or ag.agent_type not in ("sdr", "support", "closer", "manager"):
            raise HTTPException(400, "agent_id inválido (use sdr/support/closer)")
    if body.team_id:
        t = await db.get(Team, body.team_id)
        if not t or t.org_id != org_id:
            raise HTTPException(400, "team_id inválido")
    cfg = await _channel_config(db, org_id, body.channel_id)
    res = await place_call(body.to, body.script, cfg, {"agent_id": body.agent_id, "team_id": body.team_id})
    conv = Conversation(
        org_id=org_id, channel="voice", external_id=body.to,
        agent_id=body.agent_id or None, team_id=body.team_id or None,
        extra_data={"status": res.get("status"), "to": body.to},
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    db.add(Message(conversation_id=conv.id, org_id=org_id, role="assistant", content=f"[ligação {res.get('status')}] {body.script}", agent_id=body.agent_id or None))
    await db.commit()
    res["conversation_id"] = conv.id
    try:
        from aios.core.limits import track_usage

        await track_usage(org_id, db, messages=1, tokens=len(body.script) // 4, cost_usd=0.02)
    except Exception:
        pass
    return res


class RoomRequest(BaseModel):
    agent_id: str = ""
    team_id: str = ""
    channel_id: str = ""
    identity: str = ""


@router.post("/room")
async def room(
    body: RoomRequest,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Sala voz realtime (LiveKit streaming). Retorna wss + token pro browser/telefone entrar."""
    import time as _t

    import jwt as _jwt

    if not (settings.livekit_url and settings.livekit_api_key and settings.livekit_api_secret):
        raise HTTPException(409, "streaming voz desligado (LIVEKIT_URL/KEY/SECRET)")
    if body.agent_id:
        ag = await db.get(Agent, body.agent_id)
        if not ag or ag.org_id != org_id or ag.agent_type not in ("sdr", "support", "closer", "manager"):
            raise HTTPException(400, "agent_id inválido (use sdr/support/closer)")
    conv = Conversation(
        org_id=org_id, channel="voice", external_id=body.identity or "livekit-room",
        agent_id=body.agent_id or None, team_id=body.team_id or None,
        extra_data={"mode": "stream", "engine": settings.livekit_tts_engine},
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    now = int(_t.time())
    token = _jwt.encode(
        {
            "iss": settings.livekit_api_key,
            "sub": body.identity or user.id,
            "nbf": now - 5,
            "exp": now + 3600,
            "video": {"roomJoin": True, "room": conv.id, "canPublish": True, "canSubscribe": True, "canPublishData": True},
            "metadata": f'{{"agent_id": "{body.agent_id}", "org_id": "{org_id}"}}',
        },
        settings.livekit_api_secret, algorithm="HS256",
    )
    return {"ok": True, "url": settings.livekit_url, "room": conv.id, "token": token, "conversation_id": conv.id, "engine": settings.livekit_tts_engine}


@router.post("/webhook")
async def webhook(request: Request, db: DatabaseBackend = Depends(get_db_backend)):
    """Inbound do bridge SIP: {from, text?, audio_base64?, agent_id?, channel_id?}."""
    secret = request.query_params.get("secret") or request.headers.get("x-voice-secret")
    if not settings.voice_webhook_secret or not secret or secret != settings.voice_webhook_secret:
        raise HTTPException(401, "secret inválido")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "json inválido")
    text = (body.get("text") or "").strip()
    if not text and body.get("audio_base64"):
        import base64

        try:
            audio = base64.b64decode(body["audio_base64"])
        except Exception:
            raise HTTPException(400, "audio_base64 inválido")
        stt = await transcribe_audio(audio, None, body.get("language", "pt"))
        text = stt.get("text", "") if stt.get("ok") else ""
    if not text:
        raise HTTPException(400, "sem texto nem áudio")
    from_number = str(body.get("from", ""))[:30]
    channel_connection_id = ""
    if body.get("channel_id"):
        ch = await db.get(ChannelConnection, body["channel_id"])
        if ch and ch.channel_type == "voice" and ch.is_active:
            channel_connection_id = ch.id
    if not channel_connection_id:
        result = await db.execute(select(ChannelConnection).where(ChannelConnection.channel_type == "voice", ChannelConnection.is_active == True).limit(1))  # noqa: E712
        first = result.scalars().first()
        if first:
            channel_connection_id = first.id
    from aios.core.dispatch import dispatch_inbound

    await dispatch_inbound(
        channel_type="voice",
        channel_connection_id=channel_connection_id,
        conversation_id="",
        text=text,
        user_id=from_number,
        extra_data={"from_number": from_number, "agent_id": body.get("agent_id", ""), "inbound_call": True},
    )
    tts = await synthesize(text[:500])
    return {"ok": True, "status": "dispatched", "ack_audio_base64": tts.get("audio_base64") if tts.get("ok") else None}
