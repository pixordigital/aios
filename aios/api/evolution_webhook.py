"""Evolution API webhook — inbound WhatsApp messages from Evolution API.

Event-driven: webhook → dispatch → ARQ worker → agent → reply.
"""

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Request

from aios.db.backend import db_session
from aios.db.models import ChannelConnection
from aios.config import settings
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/evolution", tags=["evolution"])


@router.get("/webhook/{instance}")
async def verify_evolution_webhook(instance: str):
    """Evolution API GET verification."""
    return {"status": "ok", "instance": instance}


@router.post("/webhook/{instance}")
async def evolution_webhook(instance: str, request: Request):
    """Receive incoming WhatsApp message from Evolution API → dispatch to worker."""
    body = await request.json()

    # verify signature — fail closed: reject missing signature or unknown instance key
    sig = request.headers.get("x-evolution-signature", "")
    if not sig:
        logger.warning("Evolution webhook missing signature for instance %s", instance)
        return {"status": "ignored"}
    instance_key = await _get_evolution_api_key(instance)
    if not instance_key:
        logger.warning("Evolution webhook: no API key for instance %s — rejecting", instance)
        return {"status": "ignored"}
    if not _verify_evolution_sig(sig, body, instance_key):
        logger.warning("Evolution webhook signature mismatch for instance %s", instance)
        return {"status": "ignored"}

    # only handle new messages
    event = body.get("event", "")
    if event not in ("messages.upsert", "messages.update"):
        return {"status": "ok"}

    data = body.get("data", {})
    key = data.get("key", {})

    # skip outgoing messages
    if key.get("fromMe"):
        return {"status": "ok"}

    # extract message
    remote_jid = key.get("remoteJid", "")
    msg_from = remote_jid.split("@")[0] if remote_jid else ""

    message_data = data.get("message", {})
    msg_text = ""
    if "conversation" in message_data:
        msg_text = message_data["conversation"]
    elif "extendedTextMessage" in message_data:
        msg_text = message_data["extendedTextMessage"].get("text", "")

    if not msg_text or not msg_from:
        return {"status": "ok"}

    # find channel connection
    async with db_session() as db:
        result = await db.execute(
            select(ChannelConnection).where(
                ChannelConnection.channel_type == "evolution",
                ChannelConnection.is_active == True,
            )
        )
        conn = None
        for ch in result.scalars():
            if ch.config.get("instance") == instance:
                conn = ch
                break

        if not conn:
            logger.warning("No active Evolution channel for instance %s", instance)
            return {"status": "ok"}

    # dispatch to ARQ worker
    from aios.core.dispatch import dispatch_inbound
    await dispatch_inbound(
        channel_type="evolution",
        channel_connection_id=conn.id,
        conversation_id="",
        text=msg_text,
        user_id=msg_from,
        extra_data={"from_number": msg_from, "instance": instance},
    )

    return {"status": "ok"}


async def _get_evolution_api_key(instance_name: str) -> str:
    """Look up API key for Evolution instance from channel configs."""
    from aios.db.engine import async_session
    from sqlalchemy import select as sql_select
    try:
        async with async_session() as conn:
            result = await conn.execute(
                sql_select(ChannelConnection.config).where(
                    ChannelConnection.channel_type == "evolution",
                    ChannelConnection.is_active == True,
                )
            )
            for row in result.scalars():
                if row.get("instance") == instance_name:
                    return row.get("api_key", "")
            return ""
    except Exception:
        logger.debug("Could not fetch Evolution API key for signature check")
        return ""


def _verify_evolution_sig(signature: str, body: dict, api_key: str) -> bool:
    """Verify Evolution webhook HMAC-SHA256 signature."""
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True)
    expected = hmac.new(api_key.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)
