"""WhatsApp Cloud API channel — 100% oficial.

Send: text, media (image/doc/audio/video via url/id), template, interactive (buttons/list).
Provider switch: meta (Cloud API) | zernio (existing).
Inbound handled in aios/api/whatsapp_webhook.py — all message types.
"""

import logging
from typing import Any

from aios.channels.base import Channel, OutboundMessage

logger = logging.getLogger(__name__)


class WhatsAppChannel(Channel):
    channel_type = "whatsapp"

    def __init__(self, connection=None, agent_or_team=None, db=None):
        self.connection = connection
        self.agent_or_team = agent_or_team
        self.db = db
        self._config = connection.config if connection else {}

    async def send(self, message: OutboundMessage) -> str | None:
        if self._config.get("provider") == "zernio":
            return await self._zernio_send(message)
        return await self._meta_send(message)

    async def _meta_send(self, message: OutboundMessage) -> str | None:
        import httpx

        token = self._config.get("access_token", "")
        phone_id = self._config.get("phone_id", "")
        extra = message.extra_data or {}
        to = extra.get("from_number") or extra.get("to") or ""
        if not token or not phone_id or not to:
            logger.warning("WhatsApp send incomplete: token=%s phone=%s to=%s", bool(token), bool(phone_id), to)
            return None

        wtype = extra.get("whatsapp_type") or extra.get("type") or "text"
        base = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload: dict[str, Any] = {"messaging_product": "whatsapp", "to": to}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if wtype == "template":
                    tpl_name = extra.get("template_name") or extra.get("template") or self._config.get("template_name", "")
                    if not tpl_name:
                        logger.warning("WhatsApp template send missing template_name")
                        return None
                    tpl_lang = extra.get("template_language") or extra.get("language") or self._config.get("template_language", "pt_BR")
                    components = extra.get("template_components") or extra.get("components")
                    if not components and extra.get("template_params"):
                        params = extra["template_params"]
                        if isinstance(params, list):
                            components = [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in params]}]
                    payload["type"] = "template"
                    payload["template"] = {"name": tpl_name, "language": {"code": tpl_lang}}
                    if components:
                        payload["template"]["components"] = components

                elif wtype in ("image", "document", "audio", "video", "sticker"):
                    media_url = extra.get("media_url") or extra.get("url") or extra.get("link")
                    media_id = extra.get("media_id") or extra.get("id")
                    caption = message.text or extra.get("caption") or ""
                    filename = extra.get("filename")
                    if not media_url and not media_id:
                        logger.warning("WhatsApp media send missing url/id for %s", wtype)
                        return None
                    payload["type"] = wtype if wtype != "sticker" else "sticker"
                    media_obj: dict[str, Any] = {}
                    if media_id:
                        media_obj["id"] = media_id
                    elif media_url:
                        media_obj["link"] = media_url
                    if caption and wtype in ("image", "document", "video"):
                        media_obj["caption"] = caption[:1024]
                    if filename and wtype == "document":
                        media_obj["filename"] = filename
                    payload[wtype if wtype != "sticker" else "sticker"] = media_obj

                elif wtype == "interactive":
                    itype = extra.get("interactive_type", "button")
                    if itype == "button":
                        body_text = extra.get("body_text") or message.text or ""
                        buttons = extra.get("buttons") or []
                        if not buttons:
                            payload["type"] = "text"
                            payload["text"] = {"body": body_text}
                        else:
                            payload["type"] = "interactive"
                            payload["interactive"] = {
                                "type": "button",
                                "body": {"text": body_text[:1024]},
                                "action": {"buttons": [{"type": "reply", "reply": {"id": b.get("id", f"btn_{i}"), "title": b.get("title", "")[:20]}} for i, b in enumerate(buttons[:3])]},
                            }
                    else:
                        body_text = extra.get("body_text") or message.text or ""
                        sections = extra.get("sections") or [{"title": "Opções", "rows": extra.get("buttons", [])}]
                        payload["type"] = "interactive"
                        payload["interactive"] = {
                            "type": "list",
                            "body": {"text": body_text[:1024]},
                            "action": {"button": extra.get("button_text", "Ver opções")[:20], "sections": sections},
                        }

                elif wtype == "location":
                    lat = extra.get("latitude") or extra.get("lat")
                    lon = extra.get("longitude") or extra.get("lon")
                    if lat is not None and lon is not None:
                        payload["type"] = "location"
                        payload["location"] = {"latitude": float(lat), "longitude": float(lon), "name": extra.get("name", ""), "address": extra.get("address", "")}
                    else:
                        payload["type"] = "text"
                        payload["text"] = {"body": message.text}

                elif wtype == "contacts":
                    payload["type"] = "contacts"
                    payload["contacts"] = extra.get("contacts") or [{"name": {"formatted_name": extra.get("contact_name", "")}, "phones": [{"phone": to}]}]

                else:
                    payload["type"] = "text"
                    payload["text"] = {"preview_url": bool(extra.get("preview_url")), "body": message.text}

                resp = await client.post(base, headers=headers, json=payload)
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                if resp.status_code in (200, 201):
                    return (data.get("messages") or [{}])[0].get("id") or data.get("messages", [{}])[0].get("id")
                # handle 24h window error -> try template fallback if configured
                err = data.get("error", {}) if isinstance(data, dict) else {}
                logger.warning("WhatsApp send %s failed %d %s payload=%s", wtype, resp.status_code, str(data)[:400], str(payload)[:300])
                if err.get("code") == 131047 and self._config.get("template_name"):
                    # outside window, retry with template
                    fallback = dict(extra)
                    fallback["whatsapp_type"] = "template"
                    fallback["template_name"] = self._config.get("template_name")
                    return await self._meta_send(OutboundMessage(text=message.text, conversation_id=message.conversation_id, extra_data={**extra, **fallback}))
                return None
        except Exception:
            logger.exception("WhatsApp Cloud send error")
            return None

    async def mark_read(self, message_id: str) -> bool:
        import httpx

        token = self._config.get("access_token", "")
        phone_id = self._config.get("phone_id", "")
        if not token or not phone_id or not message_id:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"https://graph.facebook.com/v18.0/{phone_id}/messages",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"messaging_product": "whatsapp", "status": "read", "message_id": message_id},
                )
                return resp.status_code in (200, 201)
        except Exception:
            return False

    async def get_media_url(self, media_id: str) -> str | None:
        import httpx

        token = self._config.get("access_token", "")
        if not token or not media_id:
            return None
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"https://graph.facebook.com/v18.0/{media_id}", headers={"Authorization": f"Bearer {token}"})
                if resp.status_code == 200:
                    return resp.json().get("url")
        except Exception:
            pass
        return None

    async def download_media(self, media_id: str) -> bytes | None:
        url = await self.get_media_url(media_id)
        if not url:
            return None
        import httpx

        token = self._config.get("access_token", "")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
                if resp.status_code == 200:
                    return resp.content
        except Exception:
            logger.exception("download media failed %s", media_id)
        return None

    async def _zernio_send(self, message: OutboundMessage) -> str | None:
        import httpx

        api_key = self._config.get("api_key", "")
        account_id = self._config.get("account_id", "")
        if not api_key or not account_id:
            logger.warning("Zernio send incomplete: api_key=%s account=%s", bool(api_key), bool(account_id))
            return None
        base = "https://zernio.com/api/v1"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        to = (message.extra_data or {}).get("from_number", "")
        conversation_id = (message.extra_data or {}).get("conversation_id", "") or message.conversation_id
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if conversation_id:
                    resp = await client.post(f"{base}/inbox/conversations/{conversation_id}/messages", headers=headers, json={"accountId": account_id, "message": message.text})
                else:
                    if not to:
                        logger.warning("Zernio cold outreach missing recipient number")
                        return None
                    template_name = self._config.get("template_name", "")
                    if template_name:
                        payload = {"accountId": account_id, "participantId": to, "templateName": template_name, "templateLanguage": self._config.get("template_language", "en_US"), "templateParams": self._config.get("template_params_default", [])}
                    else:
                        payload = {"accountId": account_id, "participantId": to, "message": message.text, "category": "utility"}
                    resp = await client.post(f"{base}/inbox/conversations", headers=headers, json=payload)
                if resp.status_code in (200, 201):
                    data = resp.json()
                    if isinstance(data, list):
                        data = (data or [{}])[0]
                    return data.get("id") or (data.get("message") or {}).get("id")
                logger.warning("Zernio send failed: %d %s", resp.status_code, resp.text[:200])
                return None
        except Exception:
            logger.exception("Zernio send error")
            return None

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def test(self) -> dict:
        if self._config.get("provider") == "zernio":
            import httpx

            api_key = self._config.get("api_key", "")
            if not api_key:
                return {"ok": False, "message": "Missing zernio api_key"}
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get("https://zernio.com/api/v1/auth/verify", headers={"Authorization": f"Bearer {api_key}"})
                    data = resp.json()
                    if resp.status_code == 200 and data.get("valid"):
                        return {"ok": True, "message": "Zernio API key valid"}
                    return {"ok": False, "message": f"Zernio error: {data.get('error', resp.status_code)}"}
            except Exception as e:
                return {"ok": False, "message": str(e)}
        import httpx

        token = self._config.get("access_token", "")
        phone_id = self._config.get("phone_id", "")
        if not token or not phone_id:
            return {"ok": False, "message": "Missing access_token ou phone_id"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"https://graph.facebook.com/v18.0/{phone_id}", headers={"Authorization": f"Bearer {token}"})
                if resp.status_code == 200:
                    j = resp.json()
                    name = j.get("verified_name") or j.get("display_phone_number", "")
                    return {"ok": True, "message": f"WhatsApp Cloud conectado — {name or 'ok'} (phone_id {phone_id})"}
                err = resp.json().get("error", {}) if resp.headers.get("content-type", "").startswith("application/json") else {}
                return {"ok": False, "message": f"Cloud API {resp.status_code}: {err.get('message', resp.text[:120])}"}
        except Exception as e:
            logger.exception("WhatsApp test failed")
            return {"ok": False, "message": str(e)}
