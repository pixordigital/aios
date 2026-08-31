"""Zernio webhook — inbound WhatsApp messages via the Zernio unified API.

Zernio forwards WhatsApp Business messages to this endpoint with an HMAC-SHA256
signature (`X-Zernio-Signature`) over the raw body. On verify → dispatch to ARQ
worker via dispatch_inbound (same path as the Meta whatsapp webhook).
"""

import hashlib
import hmac
import logging

from fastapi import APIRouter, HTTPException, Request

from aios.config import settings
from aios.core.dispatch import dispatch_inbound
from aios.db.backend import db_session
from aios.db.models import ChannelConnection
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/zernio", tags=["zernio"])


def _zernio_matches(cfg: dict, account_id: str) -> bool:
    """True if this zernio channel is a valid route for the webhook's account.

    Reject a channel pinned to a *different* account. Accept when the channel
    doesn't pin one, the webhook doesn't name one, or they agree.
    """
    if cfg.get("provider") != "zernio":
        return False
    ch_account = cfg.get("account_id", "")
    return not ch_account or not account_id or ch_account == account_id


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
    """Receive Zernio WhatsApp message → dispatch to ARQ worker for async processing."""
    body = await request.json()

    # verify signature — fail closed: reject missing signature or unconfigured secret
    sig = request.headers.get("x-zernio-signature", "")
    if not settings.zernio_webhook_secret:
        logger.error("Zernio webhook received but AIOS_ZERNIO_WEBHOOK_SECRET not configured — rejecting")
        return {"status": "ignored"}
    if not sig:
        logger.warning("Zernio webhook missing signature")
        return {"status": "ignored"}
    raw_body = await request.body()
    expected = hmac.new(
        settings.zernio_webhook_secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        logger.warning("Zernio webhook signature mismatch")
        return {"status": "ignored"}

    event = body.get("event", "")
    if event not in ("message.received", "conversation.started"):
        return {"status": "ok"}

    msg = body.get("message") or {}
    if msg.get("direction") != "incoming":
        return {"status": "ok"}

    conversation_id = msg.get("conversationId", "")
    text = msg.get("text") or ""
    sender = msg.get("sender") or {}
    from_number = sender.get("id") or sender.get("phoneNumber") or ""
    account_id = (body.get("account") or {}).get("id", "")

    if not text or not from_number:
        return {"status": "ok"}

    try:
        from aios.core.whatsapp_guard import is_opt_out, is_opt_in, record_opt_out, record_opt_in, human_handover_needed

        low = text.strip().lower()
        if is_opt_out(low):
            record_opt_out(from_number)
            logger.info("Opt-out %s", from_number)
            return {"status": "opt-out"}
        if is_opt_in(low):
            record_opt_in(from_number)
        if human_handover_needed(text):
            logger.info("Handover %s", from_number)
    except Exception:
        pass

    # find matching active whatsapp channel configured for zernio
    async with db_session() as db:
        result = await db.execute(
            select(ChannelConnection).where(
                ChannelConnection.channel_type == "whatsapp",
                ChannelConnection.is_active == True,
            )
        )
        conn = next(
            (ch for ch in result.scalars() if _zernio_matches(ch.config or {}, account_id)),
            None,
        )
        if not conn:
            logger.warning("No active Zernio whatsapp channel for account=%s", account_id)
            return {"status": "ok"}

    await dispatch_inbound(
        channel_type="whatsapp",
        channel_connection_id=conn.id,
        conversation_id=conversation_id,
        text=text,
        user_id=from_number,
        extra_data={"from_number": from_number, "conversation_id": conversation_id, "provider": "zernio"},
    )

    return {"status": "ok"}