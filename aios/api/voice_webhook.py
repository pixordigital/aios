"""Voice webhook — LiveKit / Twilio inbound call events."""

import hashlib
import hmac
import logging

from fastapi import APIRouter, HTTPException, Request

from aios.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.post("/webhook")
async def voice_webhook(request: Request):
    """Receive voice events from LiveKit/Twilio → dispatch to agent."""
    raw_body = await request.body()

    # Verify signature if configured
    if settings.voice_webhook_secret:
        sig = request.headers.get("x-voice-signature", "")
        if not sig:
            logger.warning("Voice webhook missing signature")
            raise HTTPException(401, "Missing signature")
        expected = hmac.new(
            settings.voice_webhook_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            logger.warning("Voice webhook signature mismatch")
            raise HTTPException(401, "Invalid signature")

    try:
        body = await request.json()
    except Exception:
        body = {}

    event = body.get("event", "")
    call_sid = body.get("call_sid", body.get("call", {}).get("sid", ""))

    # Handle different event types
    if event in ("call.started", "call.incoming"):
        # Dispatch to agent for handling
        from aios.core.dispatch import dispatch_inbound

        from_number = body.get("from", body.get("caller_id", ""))
        to_number = body.get("to", body.get("called_number", ""))

        async with (await __import__("aios.db.backend", fromlist=["db_session"])).db_session() as db:
            from aios.db.models import ChannelConnection
            from sqlalchemy import select

            result = await db.execute(
                select(ChannelConnection).where(
                    ChannelConnection.channel_type == "voice",
                    ChannelConnection.is_active == True,
                )
            )
            conn = result.scalars().first()

            if conn:
                await dispatch_inbound(
                    channel_type="voice",
                    channel_connection_id=conn.id,
                    conversation_id="",
                    text=f"Incoming call from {from_number} to {to_number}",
                    user_id=from_number,
                    extra_data={
                        "event": event,
                        "call_sid": call_sid,
                        "from_number": from_number,
                        "to_number": to_number,
                        "direction": "inbound",
                    },
                )

    elif event in ("call.ended", "call.completed"):
        logger.info("Call ended: %s", call_sid)
        # Could update conversation status here

    return {"status": "ok"}


@router.get("/webhook")
async def voice_webhook_verify():
    """Health check / verification endpoint."""
    return {"status": "ok", "service": "voice-webhook"}