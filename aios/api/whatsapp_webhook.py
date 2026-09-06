"""WhatsApp Cloud API webhook — 100% tipos.

Inbound: text, image, audio/voice, document, video, sticker, location, contacts, interactive (button/list), reaction.
Status: sent/delivered/read/failed (log only).
Dispatch: cada mensagem → dispatch_inbound para agente.
"""

import hashlib
import hmac
import logging

from fastapi import APIRouter, HTTPException, Request

from aios.config import settings

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


def _parse_message(msg: dict) -> tuple[str, dict]:
    mtype = msg.get("type", "")
    extra: dict = {"whatsapp_raw": msg, "whatsapp_type": mtype, "message_id": msg.get("id", "")}
    text = ""
    if mtype == "text":
        text = (msg.get("text") or {}).get("body", "")
    elif mtype == "image":
        img = msg.get("image") or {}
        text = img.get("caption") or "[imagem]"
        extra.update({"media_id": img.get("id"), "media_mime": img.get("mime_type"), "caption": img.get("caption", "")})
    elif mtype in ("audio", "voice"):
        aud = msg.get("audio") or msg.get("voice") or {}
        text = "[áudio]"
        extra.update({"media_id": aud.get("id"), "media_mime": aud.get("mime_type"), "voice": aud.get("voice", False)})
    elif mtype == "document":
        doc = msg.get("document") or {}
        text = doc.get("caption") or f"[documento: {doc.get('filename','')}]"
        extra.update({"media_id": doc.get("id"), "filename": doc.get("filename"), "media_mime": doc.get("mime_type")})
    elif mtype == "video":
        vid = msg.get("video") or {}
        text = vid.get("caption") or "[vídeo]"
        extra.update({"media_id": vid.get("id"), "media_mime": vid.get("mime_type"), "caption": vid.get("caption", "")})
    elif mtype == "sticker":
        stk = msg.get("sticker") or {}
        text = "[figurinha]"
        extra.update({"media_id": stk.get("id"), "media_mime": stk.get("mime_type")})
    elif mtype == "location":
        loc = msg.get("location") or {}
        text = f"[localização: {loc.get('latitude')},{loc.get('longitude')}]"
        extra.update({"latitude": loc.get("latitude"), "longitude": loc.get("longitude"), "name": loc.get("name"), "address": loc.get("address")})
    elif mtype == "contacts":
        contacts = msg.get("contacts") or []
        names = [c.get("name", {}).get("formatted_name", "") for c in contacts]
        text = f"[contato: {', '.join(names)}]"
        extra["contacts"] = contacts
    elif mtype == "interactive":
        inter = msg.get("interactive") or {}
        itype = inter.get("type")
        if itype == "button_reply":
            br = inter.get("button_reply") or {}
            text = br.get("title", "") or br.get("id", "")
            extra.update({"button_id": br.get("id"), "button_title": br.get("title")})
        elif itype == "list_reply":
            lr = inter.get("list_reply") or {}
            text = lr.get("title", "") or lr.get("id", "")
            extra.update({"list_id": lr.get("id"), "list_title": lr.get("title"), "list_description": lr.get("description")})
        else:
            text = str(inter)
    elif mtype == "button":
        btn = msg.get("button") or {}
        text = btn.get("text", "") or btn.get("payload", "")
        extra.update({"button_text": text, "button_payload": btn.get("payload")})
    elif mtype == "reaction":
        react = msg.get("reaction") or {}
        text = react.get("emoji", "")
        extra.update({"reaction": react})
    elif mtype == "order":
        text = "[pedido]"
        extra["order"] = msg.get("order")
    else:
        text = msg.get("text", {}).get("body", "") if isinstance(msg.get("text"), dict) else str(msg.get("body", "")) or f"[{mtype}]"
    return text, extra


@router.post("/webhook")
async def inbound_webhook(request: Request):
    raw_body = await request.body()
    try:
        body = await request.json()
    except Exception:
        body = {}

    sig = request.headers.get("x-hub-signature-256", "")
    if not settings.whatsapp_app_secret:
        logger.error("WhatsApp webhook sem AIOS_WHATSAPP_APP_SECRET — rejeitando")
        return {"status": "ignored"}
    if not sig:
        logger.warning("WhatsApp webhook sem assinatura")
        return {"status": "ignored"}
    expected = "sha256=" + hmac.new(settings.whatsapp_app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        logger.warning("WhatsApp assinatura inválida")
        return {"status": "ignored"}

    entries = body.get("entry") or []
    dispatched = 0
    for entry in entries:
        for change in entry.get("changes") or []:
            value = change.get("value", {}) or {}
            metadata = value.get("metadata") or {}
            phone_id = metadata.get("phone_number_id", "")
            # statuses — apenas log, não despacha para agente
            for st in value.get("statuses") or []:
                logger.info("WhatsApp status %s msg=%s to=%s phone_id=%s", st.get("status"), st.get("id"), st.get("recipient_id"), phone_id)
                # opcional: atualizar WorkflowRun/DeadLetter tracking aqui

            contacts = {c.get("wa_id"): c for c in value.get("contacts") or []}

            for msg in value.get("messages") or []:
                from_number = msg.get("from", "")
                msg_id = msg.get("id", "")
                text, extra = _parse_message(msg)
                if not text and not extra.get("media_id"):
                    continue
                extra.update({"from_number": from_number, "phone_id": phone_id, "message_id": msg_id})
                if from_number in contacts:
                    extra["contact_name"] = contacts[from_number].get("profile", {}).get("name", "")
                # transcrição voz → texto
                if extra.get("media_id") and extra.get("whatsapp_type") in ("audio","voice"):
                    try:
                        from aios.tools.transcribe import TranscribeTool
                        tr = await TranscribeTool().run(media_id=extra["media_id"], language="pt")
                        if tr.get("text"):
                            text = tr["text"]
                            extra["transcribed"] = text
                            extra["original_type"] = "voice"
                    except Exception:
                        pass

                # marca como lido (best-effort, não bloqueia)
                try:
                    from aios.db.backend import db_session
                    from aios.db.models import ChannelConnection
                    from sqlalchemy import select

                    async with db_session() as db:
                        result = await db.execute(select(ChannelConnection).where(ChannelConnection.channel_type == "whatsapp", ChannelConnection.is_active == True))
                        conn = None
                        for ch in result.scalars():
                            if ch.config.get("phone_id") == phone_id or phone_id == "":
                                conn = ch
                                break
                        if not conn:
                            logger.warning("Sem canal WhatsApp para phone_id=%s", phone_id)
                            continue

                        # auto-mark read
                        try:
                            from aios.channels.whatsapp import WhatsAppChannel

                            ch_obj = WhatsAppChannel(connection=conn)
                            await ch_obj.mark_read(msg_id)
                        except Exception:
                            pass

                        from aios.core.dispatch import dispatch_inbound

                        await dispatch_inbound(
                            channel_type="whatsapp",
                            channel_connection_id=conn.id,
                            conversation_id="",
                            text=text,
                            user_id=from_number,
                            extra_data=extra,
                        )
                        dispatched += 1
                except Exception:
                    logger.exception("Falha dispatch whatsapp %s", msg_id)

    return {"status": "ok", "dispatched": dispatched}
