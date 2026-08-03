"""WhatsApp Cloud API webhook - inbound messages.

Event-driven: webhook receives message → dispatches to ARQ worker → agent processes → reply delivered.
"""

import hashlib
import hmac
import logging

from fastapi import APIRouter, HTTPException, Request

from aios.channels.base import InboundMessage, OutboundMessage
from aios.channels.manager import manager as channel_mgr
from aios.core.limits import check_org_limits, track_usage
from aios.db.backend import db_session
from aios.db.models import Agent, ChannelConnection, Conversation, Message, Team
from aios.config import settings
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

@router.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if mode == "subscribe" and token == settings.whatsapp_verify_token and challenge:
        return int(challenge)
    raise HTTPException(403, "Falha na verificação")


@router.post("/webhook")
async def inbound_webhook(request: Request):
    """Receive WhatsApp message → dispatch to ARQ worker for async processing."""
    body = await request.json()

    # verify signature — fail closed: reject missing signature or unconfigured secret
    sig = request.headers.get("x-hub-signature-256", "")
    if not settings.whatsapp_app_secret:
        logger.error("WhatsApp webhook received but AIOS_WHATSAPP_APP_SECRET not configured — rejecting")
        return {"status": "ignored"}
    if not sig:
        logger.warning("WhatsApp webhook missing signature")
        return {"status": "ignored"}
    raw_body = await request.body()
    expected = "sha256=" + hmac.new(
        settings.whatsapp_app_secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        logger.warning("WhatsApp webhook signature mismatch")
        return {"status": "ignored"}

    # extract message
    entry = (body.get("entry") or [{}])[0]
    change = (entry.get("changes") or [{}])[0]
    value = change.get("value", {})
    messages = value.get("messages") or []
    if not messages:
        return {"status": "ok"}

    msg = messages[0]
    from_number = msg.get("from", "")
    msg_text = ""
    if msg.get("type") == "text":
        msg_text = (msg.get("text") or {}).get("body", "")

    if not msg_text:
        return {"status": "ok"}

    # find matching channel connection
    phone_id = (value.get("metadata") or {}).get("phone_number_id", "")
    async with db_session() as db:
        result = await db.execute(
            select(ChannelConnection).where(
                ChannelConnection.channel_type == "whatsapp",
                ChannelConnection.is_active == True,
            )
        )
        conn = None
        for ch in result.scalars():
            if ch.config.get("phone_id") == phone_id or phone_id == "":
                conn = ch
                break

        if not conn:
            logger.warning("No active WhatsApp channel for phone_id=%s", phone_id)
            return {"status": "ok"}

    # dispatch to ARQ worker (non-blocking)
    from aios.core.dispatch import dispatch_inbound
    await dispatch_inbound(
        channel_type="whatsapp",
        channel_connection_id=conn.id,
        conversation_id="",
        text=msg_text,
        user_id=from_number,
        extra_data={"from_number": from_number, "phone_id": phone_id},
    )

    return {"status": "ok"}
