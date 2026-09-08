"""Evolution API WhatsApp channel — unified Baileys + Meta Cloud API."""

import asyncio
import logging
import random
from typing import Any

import httpx

from aios.channels.base import Channel, OutboundMessage
from aios.config import settings

logger = logging.getLogger(__name__)


class EvolutionChannel(Channel):
    """Unified WhatsApp channel via Evolution API.

    Supports:
    - provider="baileys": WhatsApp Web (Evolution default)
    - provider="meta": Meta Cloud API (official Business API)

    Multi-tenant: one Evolution instance per client org.
    Paid plans can have multiple instances.
    """

    channel_type = "evolution"

    def __init__(self, connection=None, agent_or_team=None, db=None):
        self.connection = connection
        self.agent_or_team = agent_or_team
        self.db = db
        self._config = connection.config if connection else {}

    @property
    def provider(self) -> str:
        """Provider mode: 'baileys' (default) or 'meta'."""
        return self._config.get("provider", "baileys")

    @property
    def instance(self) -> str:
        return self._config.get("instance", "")

    @property
    def api_key(self) -> str:
        return self._config.get("api_key", "")

    @property
    def base_url(self) -> str:
        return self._config.get("server_url", "http://evolution:8080").rstrip("/")

    async def send(self, message: OutboundMessage) -> str | None:
        if self.provider == "meta":
            return await self._send_meta(message)
        return await self._send_baileys(message)

    async def _send_baileys(self, message: OutboundMessage) -> str | None:
        """Send via Baileys (WhatsApp Web)."""
        if not self.instance or not self.api_key:
            logger.warning("Evolution Baileys not configured: instance=%s", self.instance)
            return None

        if not await self._validate_url():
            return None

        to = (message.extra_data or {}).get("from_number") or self._config.get("default_number", "")
        if not to:
            logger.warning("No recipient number for Evolution Baileys send")
            return None

        try:
            from aios.core.whatsapp_guard import guard_send, humanize_delay, vary_text, record_ban_signal
            varied = vary_text(message.text)
            if varied != message.text:
                message.text = varied
            ok, reason = await guard_send(to, message.text, provider="evolution", instance=self.instance)
            if not ok:
                logger.warning("Evolution guard block %s: %s", to, reason)
                if "global" in reason or "warmup" in reason:
                    record_ban_signal(to, 30)
                return None
        except Exception:
            pass

        try:
            delay = (await humanize_delay(message.text)) if callable(humanize_delay) else 0
            await asyncio.sleep(delay + random.uniform(0.5, 1.5))

            async with httpx.AsyncClient(timeout=30) as client:
                try:
                    await client.post(
                        f"{self.base_url}/chat/whatsappNumbers/{self.instance}",
                        headers={"apikey": self.api_key},
                        json={"numbers": [to]},
                    )
                except Exception:
                    pass
                try:
                    await client.post(
                        f"{self.base_url}/chat/updatePresence/{self.instance}",
                        headers={"apikey": self.api_key},
                        json={"number": to, "presence": "composing"},
                    )
                    await asyncio.sleep(random.uniform(1.0, 2.5))
                except Exception:
                    pass

                resp = await client.post(
                    f"{self.base_url}/message/sendText/{self.instance}",
                    headers={"apikey": self.api_key, "Content-Type": "application/json"},
                    json={
                        "number": to,
                        "textMessage": {"text": message.text},
                        "options": {"delay": int(delay * 1000), "presence": "composing"},
                    },
                )

                if resp.status_code in (200, 201):
                    data = resp.json()
                    msg_key = data.get("key", {})
                    return msg_key.get("id") or msg_key.get("remoteJid")

                if resp.status_code in (401, 403, 429):
                    txt = resp.text[:500].lower()
                    if any(k in txt for k in ["ban", "blocked", "forbidden", "rate"]):
                        record_ban_signal(to, 120)
                        logger.warning("Evolution Baileys ban signal %s: %d %s", to, resp.status_code, txt[:200])

                logger.warning("Evolution Baileys send failed: %d %s", resp.status_code, resp.text[:500])
                return None
        except Exception:
            logger.exception("Evolution Baileys send error")
            return None

    async def _send_meta(self, message: OutboundMessage) -> str | None:
        """Send via Meta Cloud API (through Evolution API bridge)."""
        if not self.instance or not self.api_key:
            logger.warning("Evolution Meta not configured: instance=%s", self.instance)
            return None

        if not await self._validate_url():
            return None

        to = (message.extra_data or {}).get("from_number") or self._config.get("default_number", "")
        if not to:
            logger.warning("No recipient number for Evolution Meta send")
            return None

        extra = message.extra_data or {}
        wtype = extra.get("whatsapp_type") or extra.get("type") or "text"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                payload = self._build_meta_payload(wtype, to, message.text, extra)
                if not payload:
                    return None

                resp = await client.post(
                    f"{self.base_url}/message/sendWhatsApp/{self.instance}",
                    headers={"apikey": self.api_key, "Content-Type": "application/json"},
                    json=payload,
                )

                if resp.status_code in (200, 201):
                    data = resp.json()
                    return data.get("key", {}).get("id") or data.get("messageId")

                logger.warning("Evolution Meta send failed: %d %s", resp.status_code, resp.text[:500])
                return None
        except Exception:
            logger.exception("Evolution Meta send error")
            return None

    def _build_meta_payload(self, wtype: str, to: str, text: str, extra: dict) -> dict | None:
        """Build Evolution Meta Cloud API payload."""
        payload: dict[str, Any] = {"number": to}

        if wtype == "template":
            tpl_name = extra.get("template_name") or self._config.get("template_name", "")
            if not tpl_name:
                logger.warning("Evolution Meta template send missing template_name")
                return None
            tpl_lang = extra.get("template_language") or self._config.get("template_language", "pt_BR")
            components = extra.get("template_components")
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
            caption = text or extra.get("caption") or ""
            filename = extra.get("filename")
            if not media_url and not media_id:
                logger.warning("Evolution Meta media send missing url/id for %s", wtype)
                return None
            payload["mediatype"] = wtype
            media_obj: dict[str, Any] = {}
            if media_id:
                media_obj["id"] = media_id
            elif media_url:
                media_obj["link"] = media_url
            if caption and wtype in ("image", "document", "video"):
                media_obj["caption"] = caption[:1024]
            if filename and wtype == "document":
                media_obj["filename"] = filename
            payload["media"] = media_obj

        elif wtype == "interactive":
            itype = extra.get("interactive_type", "button")
            if itype == "button":
                body_text = extra.get("body_text") or text or ""
                buttons = extra.get("buttons") or []
                if not buttons:
                    payload["type"] = "text"
                    payload["text"] = body_text
                else:
                    payload["type"] = "interactive"
                    payload["interactive"] = {
                        "type": "button",
                        "body": {"text": body_text[:1024]},
                        "action": {"buttons": [{"type": "reply", "reply": {"id": b.get("id", f"btn_{i}"), "title": b.get("title", "")[:20]}} for i, b in enumerate(buttons[:3])]},
                    }
            else:
                body_text = extra.get("body_text") or text or ""
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
                payload["text"] = text

        elif wtype == "contacts":
            payload["type"] = "contacts"
            payload["contacts"] = extra.get("contacts") or [{"name": {"formatted_name": extra.get("contact_name", "")}, "phones": [{"phone": to}]}]

        else:
            payload["type"] = "text"
            payload["text"] = text

        return payload

    async def _validate_url(self) -> bool:
        from urllib.parse import urlparse
        from aios.tools.http_get import _is_private
        host = urlparse(self.base_url).hostname
        if not host or _is_private(host):
            logger.warning("Evolution send blocked: private server_url (%s)", host)
            return False
        return True

    async def create_instance(self, instance_name: str, provider: str = "baileys", **kwargs) -> dict:
        """Create new Evolution instance (multi-tenant provisioning).

        Enforces plan-based instance limits.
        """
        if not self.api_key:
            return {"ok": False, "message": "Missing api_key for provisioning"}

        # Check plan limit
        limit_check = await self._check_instance_limit()
        if not limit_check["ok"]:
            return limit_check

        payload = {
            "instanceName": instance_name,
            "provider": provider,
            "qrcode": True,
            "integration": "WHATSAPP-BAILEYS" if provider == "baileys" else "WHATSAPP-BUSINESS",
            **kwargs,
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.base_url}/instance/create",
                    headers={"apikey": self.api_key, "Content-Type": "application/json"},
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    return {"ok": True, "data": resp.json()}
                return {"ok": False, "message": f"{resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            logger.exception("Evolution create_instance error")
            return {"ok": False, "message": str(e)}

    async def _check_instance_limit(self) -> dict:
        """Check if org has reached max Evolution instances for their plan."""
        if not self.db or not self.connection:
            return {"ok": True}  # skip check if no db/connection

        try:
            org_id = self.connection.org_id
            if not org_id:
                return {"ok": True}

            # Count existing evolution channels for this org
            from aios.db.models import ChannelConnection
            from sqlalchemy import select, func

            result = await self.db.execute(
                select(func.count(ChannelConnection.id)).where(
                    ChannelConnection.org_id == org_id,
                    ChannelConnection.channel_type == "evolution",
                    ChannelConnection.is_active == True,
                )
            )
            current_count = result.scalar() or 0

            # Get org's plan
            from aios.db.models import Organization
            org = await self.db.get(Organization, org_id)
            if not org:
                return {"ok": True}

            from aios.config import PLANS
            plan = PLANS.get(org.plan, PLANS["free"])
            max_instances = plan.get("max_evolution_instances", 0)

            if max_instances > 0 and current_count >= max_instances:
                return {
                    "ok": False,
                    "message": f"Limite de instâncias WhatsApp atingido ({current_count}/{max_instances}). Plano {plan['name']} permite {max_instances} instância(s). Faça upgrade para mais."
                }

            return {"ok": True}
        except Exception as e:
            logger.warning("Instance limit check failed: %s", e)
            return {"ok": True}  # fail open

    async def delete_instance(self, instance_name: str) -> dict:
        """Delete Evolution instance."""
        if not self.api_key:
            return {"ok": False, "message": "Missing api_key"}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.delete(
                    f"{self.base_url}/instance/delete/{instance_name}",
                    headers={"apikey": self.api_key},
                )
                return {"ok": resp.status_code in (200, 201, 204), "message": resp.text[:200] if resp.status_code >= 400 else "Deleted"}
        except Exception as e:
            logger.exception("Evolution delete_instance error")
            return {"ok": False, "message": str(e)}

    async def list_instances(self) -> dict:
        """List all Evolution instances."""
        if not self.api_key:
            return {"ok": False, "message": "Missing api_key"}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.base_url}/instance/fetchInstances",
                    headers={"apikey": self.api_key},
                )
                if resp.status_code == 200:
                    return {"ok": True, "instances": resp.json()}
                return {"ok": False, "message": f"{resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            logger.exception("Evolution list_instances error")
            return {"ok": False, "message": str(e)}

    async def get_instance_qrcode(self, instance_name: str) -> dict:
        """Get QR code for Baileys instance connection."""
        if not self.api_key:
            return {"ok": False, "message": "Missing api_key"}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.base_url}/instance/connect/{instance_name}",
                    headers={"apikey": self.api_key},
                )
                if resp.status_code == 200:
                    return {"ok": True, "data": resp.json()}
                return {"ok": False, "message": f"{resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            logger.exception("Evolution get_instance_qrcode error")
            return {"ok": False, "message": str(e)}

    async def start(self) -> None:
        logger.info("Evolution API channel %s (%s) ready", self.instance, self.provider)

    async def stop(self) -> None:
        pass

    async def test(self) -> dict:
        if not await self._validate_url():
            return {"ok": False, "message": "server_url must be a public URL"}

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.base_url}/instance/fetchInstances",
                    headers={"apikey": self.api_key},
                )
                if resp.status_code == 200:
                    instances = resp.json()
                    found = any(i.get("name") == self.instance for i in (instances if isinstance(instances, list) else []))
                    if found:
                        return {"ok": True, "message": f"Instance '{self.instance}' found and API connected ({self.provider})"}
                    return {"ok": True, "message": f"API connected ({self.provider}) — instance check skipped"}
                return {"ok": False, "message": f"API error: {resp.status_code}"}
        except Exception as e:
            logger.exception("Evolution API test failed")
            return {"ok": False, "message": str(e)}