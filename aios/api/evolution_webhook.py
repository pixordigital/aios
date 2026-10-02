"""Evolution API webhook — unified inbound for Baileys + Meta Cloud API."""

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
    """Receive incoming WhatsApp message from Evolution API → dispatch to worker.

    Handles both Baileys (WhatsApp Web) and Meta Cloud API events.
    Routes by instance name — single webhook endpoint for all providers.
    """
    body = await request.json()

    # Authenticate the caller — fail closed, and say so loudly.
    #
    # Evolution API does NOT sign request bodies. Its `webhookAuth` config sends
    # a static shared secret in a request header. The previous code required an
    # x-evolution-signature header and compared it to HMAC(api_key, canonical_json),
    # which no Evolution version produces — so every inbound message was dropped
    # with a log line nobody was watching.
    instance_key = await _get_evolution_api_key(instance)
    if not instance_key:
        logger.error(
            "Evolution webhook: no configured instance %r (is the channel active?) — rejecting", instance
        )
        return {"status": "ignored", "reason": "unknown_instance"}

    request.state.aios_body = body
    if not _verify_request(request, instance_key):
        logger.error(
            "Evolution webhook: auth failed for instance %r — rejecting", instance
        )
        return {"status": "ignored", "reason": "auth_failed"}

    # normalize event (Baileys and Meta have different event names)
    event = body.get("event", "")
    data = body.get("data", {})

    # extract message based on provider format
    msg_text, msg_from, msg_id = _parse_message(data, event)
    if not msg_text or not msg_from:
        return {"status": "ok"}

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

    # Resolve the org before handling consent: an opt-out that lives only in
    # process memory is forgotten on the next deploy, and then the number gets
    # messaged again. Persistence needs the org id, so it happens here.
    org_id = conn.org_id

    try:
        from aios.core.whatsapp_guard import (
            human_handover_needed,
            is_opt_in,
            is_opt_out,
            persist_opt_in,
            persist_opt_out,
            record_opt_in,
            record_opt_out,
        )

        low = msg_text.strip().lower()
        if is_opt_out(low):
            record_opt_out(msg_from)
            await persist_opt_out(org_id, msg_from)
            logger.info("Evolution opt-out %s (persisted)", msg_from)
            return {"status": "opt-out"}
        if is_opt_in(low):
            record_opt_in(msg_from)
            await persist_opt_in(org_id, msg_from)
        if human_handover_needed(msg_text):
            logger.info("Evolution handover %s", msg_from)
    except Exception:
        logger.exception("Evolution consent handling failed for %s", msg_from)

    # dispatch to ARQ worker
    from aios.core.dispatch import dispatch_inbound
    await dispatch_inbound(
        channel_type="evolution",
        channel_connection_id=conn.id,
        conversation_id="",
        text=msg_text,
        user_id=msg_from,
        extra_data={"from_number": msg_from, "instance": instance, "msg_id": msg_id},
    )

    return {"status": "ok"}


def _parse_message(data: dict, event: str) -> tuple[str, str, str]:
    """Parse message from Evolution webhook payload.

    Supports:
    - Baileys: messages.upsert / messages.update
    - Meta Cloud API: messages.upsert (via Evolution bridge)

    Returns: (text, from_number, message_id)
    """
    msg_text = ""
    msg_from = ""
    msg_id = ""

    key = data.get("key", {})
    message_data = data.get("message", {})

    # skip outgoing messages
    if key.get("fromMe"):
        return "", "", ""

    # Baileys format
    if "conversation" in message_data:
        msg_text = message_data["conversation"]
    elif "extendedTextMessage" in message_data:
        msg_text = message_data["extendedTextMessage"].get("text", "")
    elif "imageMessage" in message_data:
        msg_text = f"[imagem] {message_data['imageMessage'].get('caption', '')}"
    elif "documentMessage" in message_data:
        msg_text = f"[documento] {message_data['documentMessage'].get('caption', '')}"
    elif "audioMessage" in message_data:
        msg_text = "[áudio]"
    elif "videoMessage" in message_data:
        msg_text = f"[vídeo] {message_data['videoMessage'].get('caption', '')}"
    elif "stickerMessage" in message_data:
        msg_text = "[sticker]"
    elif "locationMessage" in message_data:
        loc = message_data["locationMessage"]
        msg_text = f"[localização] {loc.get('name', '')} {loc.get('address', '')}"
    elif "contactMessage" in message_data:
        msg_text = "[contato]"

    # Meta Cloud API format (via Evolution bridge)
    elif "type" in message_data:
        mtype = message_data["type"]
        if mtype == "text":
            msg_text = message_data.get("text", {}).get("body", "")
        elif mtype in ("image", "document", "video", "audio"):
            msg_text = f"[{mtype}] {message_data.get(mtype, {}).get('caption', '')}"
        elif mtype == "interactive":
            interactive = message_data.get("interactive", {})
            if interactive.get("type") == "button_reply":
                msg_text = interactive.get("button_reply", {}).get("title", "")
            elif interactive.get("type") == "list_reply":
                msg_text = interactive.get("list_reply", {}).get("title", "")
        elif mtype == "location":
            loc = message_data.get("location", {})
            msg_text = f"[localização] {loc.get('name', '')} {loc.get('address', '')}"
        elif mtype == "contacts":
            msg_text = "[contato]"

    remote_jid = key.get("remoteJid", "")
    msg_from = remote_jid.split("@")[0] if remote_jid else ""

    # message ID
    msg_id = key.get("id", "") or data.get("messageId", "")

    return msg_text, msg_from, msg_id


async def _get_evolution_api_key(instance_name: str) -> str:
    """Look up API key for Evolution instance from channel configs. Org-isolated."""
    from aios.db.engine import async_session
    from sqlalchemy import select as sql_select
    try:
        async with async_session() as conn:
            result = await conn.execute(
                sql_select(ChannelConnection.config, ChannelConnection.org_id).where(
                    ChannelConnection.channel_type == "evolution",
                    ChannelConnection.is_active == True,
                )
            )
            for config, org_id in result.all():
                if config.get("instance") == instance_name:
                    # ensure instance name is namespaced or unique per org
                    return config.get("api_key", "")
            return ""
    except Exception:
        logger.debug("Could not fetch Evolution API key for signature check")
        return ""


# Header Evolution's `webhookAuth` uses to send the shared secret.
_AUTH_HEADERS = ("x-webhook-auth", "x-evolution-auth", "x-evolution-signature")


def _verify_request(request, api_key: str) -> bool:
    """Authenticate an Evolution webhook call.

    Primary path is the shared secret Evolution actually sends in a header
    (`webhookAuth`). The HMAC-of-body path is kept for deployments that front
    Evolution with a proxy that does sign, but it is no longer the only option.
    """
    if not api_key:
        return False

    for header in _AUTH_HEADERS:
        got = request.headers.get(header, "")
        if got and hmac.compare_digest(got, api_key):
            return True

    sig = request.headers.get("x-evolution-signature", "")
    if sig and isinstance(getattr(request, "state", None), object):
        body = getattr(request.state, "aios_body", None)
        if isinstance(body, dict):
            return _verify_evolution_sig(sig, body, api_key)

    return False


def _verify_evolution_sig(signature: str, body: dict, api_key: str) -> bool:
    """Verify HMAC-SHA256 over the canonical body (proxy-fronted deployments)."""
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True)
    expected = hmac.new(api_key.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)