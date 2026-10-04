"""Evolution API webhook — unified inbound for Baileys + Meta Cloud API."""

import hashlib
import time
import hmac
import json
import logging

from fastapi import APIRouter, Request

from aios.db.backend import db_session
from aios.db.models import ChannelConnection
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
    try:
        raw = await request.body()
    except Exception:
        raw = b""
    # Starlette caches the body, so this costs nothing and gives the verifier
    # the exact bytes Evolution signed. Signing a re-serialised dict instead
    # changed whitespace and key order and broke every proxy-fronted deployment.
    request.state.aios_raw = raw
    try:
        parsed = json.loads(raw or b"{}")
        body = parsed if isinstance(parsed, dict) else {}
    except Exception:
        # Form posts, empty bodies and truncated chunks used to 500 here before
        # authentication was even reached.
        body = {}
    request.state.aios_body = body

    # Authenticate FIRST, before looking at the payload at all. Parsing before
    # auth meant an empty body short-circuited to `{"status": "ok"}` without
    # ever being checked, so an unauthenticated caller could tell configured
    # instances from unconfigured ones.
    #
    # Evolution API does NOT sign request bodies. Its `webhookAuth` config sends
    # a static shared secret in a request header. The previous code required an
    # x-evolution-signature header and compared it to HMAC(api_key, canonical_json),
    # which no Evolution version produces — so every inbound message was dropped
    # with a log line nobody was watching.
    #
    # One lookup for both the credential and the channel: reading the row twice
    # meant auth judged a different snapshot than the dispatch used.
    async with db_session() as db:
        conn = await _resolve_channel(db, instance)
        instance_key = _channel_api_key(conn)
        # Copy out of the session: these are read after the block closes.
        channel_id = conn.id if conn else ""
        org_id = conn.org_id if conn else ""

    if not instance_key:
        logger.error(
            "Evolution webhook: instance %r has no configured channel or api_key "
            "— rejecting", instance
        )
        # Same shape as an auth failure. Distinct reasons let anyone enumerate
        # which instance names exist by watching which error comes back.
        return {"status": "ignored", "reason": "unauthorized"}

    if not _verify_request(request, instance_key):
        logger.error(
            "Evolution webhook: auth failed for instance %r — rejecting", instance
        )
        return {"status": "ignored", "reason": "unauthorized"}

    # normalize event (Baileys and Meta have different event names)
    event = body.get("event", "")
    data = body.get("data", {})

    # extract message based on provider format
    msg_text, msg_from, msg_id = _parse_message(data, event)
    if not msg_text or not msg_from:
        return {"status": "ok"}

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
    _extra: dict[str, object] = {"from_number": msg_from, "instance": instance, "msg_id": msg_id}
    # Voice notes arrive as "[áudio]" text; without the media key the bytes are
    # unrecoverable and the transcribe tool has nothing to fetch. Stash what a
    # download needs so the capability actually exists.
    try:
        _audio = (data.get("message") or {}).get("audioMessage") or {}
        if isinstance(_audio, dict) and (_audio.get("url") or _audio.get("mediaKey")):
            _extra["audio_media"] = {
                "url": _audio.get("url", ""),
                "media_key": _audio.get("mediaKey", ""),
                "mimetype": _audio.get("mimetype", ""),
                "seconds": _audio.get("seconds", 0),
            }
    except Exception:
        pass
    await dispatch_inbound(
        channel_type="evolution",
        channel_connection_id=channel_id,
        conversation_id="",
        text=msg_text,
        user_id=msg_from,
        extra_data=_extra,
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


async def _resolve_channel(db, instance_name: str):
    """Find the active Evolution channel for `instance_name`.

    Scoped in SQL rather than by scanning every tenant's config blob. Ambiguous
    instance names (two orgs both using `default`) resolve to the lowest id, so
    the winner is at least deterministic instead of depending on row order.
    """
    result = await db.execute(
        select(ChannelConnection)
        .where(
            ChannelConnection.channel_type == "evolution",
            ChannelConnection.is_active == True,  # noqa: E712
            ChannelConnection.config["instance"].as_string() == instance_name,
        )
        .order_by(ChannelConnection.id)
        .limit(1)
    )
    return result.scalars().first()


def _channel_api_key(conn) -> str:
    """Decrypted Evolution API key for a channel.

    Channels created through the dashboard store the key as `enc:<fernet>`, so
    the raw config value is not the secret Evolution sends in the webhook
    header. Comparing the header against the ciphertext failed auth for every
    dashboard-created channel while the API-created ones worked — which is why
    this looked healthy in tests.
    """
    if not conn:
        return ""
    raw = (conn.config or {}).get("api_key", "")
    if not raw:
        return ""
    if not str(raw).startswith("enc:"):
        return raw
    from aios.core.secrets import decrypt_channel_config
    try:
        return decrypt_channel_config({"api_key": raw}).get("api_key", "")
    except Exception:
        logger.error(
            "Evolution channel %s: api_key could not be decrypted "
            "(is AIOS_ENCRYPTION_KEY still the one it was stored with?)",
            getattr(conn, "id", "?"),
        )
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

    # Replay window. Evolution sends x-evolution-timestamp; without this a
    # single captured request replays forever and bills agent runs for messages
    # that never existed.
    ts = request.headers.get("x-evolution-timestamp", "")
    if ts:
        try:
            if abs(time.time() - int(ts)) > 300:
                return False
        except (TypeError, ValueError):
            return False

    sig = request.headers.get("x-evolution-signature", "")
    if sig and isinstance(getattr(request, "state", None), object):
        raw = getattr(request.state, "aios_raw", None)
        if isinstance(raw, bytes):
            return _verify_evolution_sig(sig, raw, api_key)

    return False


def _verify_evolution_sig(signature: str, raw: bytes, api_key: str) -> bool:
    """Verify HMAC-SHA256 over the raw request bytes (proxy-fronted deployments)."""
    expected = hmac.new(api_key.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)