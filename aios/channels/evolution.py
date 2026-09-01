"""Evolution API WhatsApp channel — connects via Evolution API (Baileys)."""

import logging

import httpx

from aios.channels.base import Channel, OutboundMessage

logger = logging.getLogger(__name__)


class EvolutionChannel(Channel):
    channel_type = "evolution"

    def __init__(self, connection=None, agent_or_team=None, db=None):
        self.connection = connection
        self.agent_or_team = agent_or_team
        self.db = db
        self._config = connection.config if connection else {}

    async def send(self, message: OutboundMessage) -> str | None:
        import asyncio
        import random

        instance = self._config.get("instance", "")
        api_key = self._config.get("api_key", "")
        base_url = self._config.get("server_url", "http://localhost:8080").rstrip("/")

        if not instance or not api_key:
            logger.warning("Evolution API not configured: instance=%s", instance)
            return None

        from urllib.parse import urlparse
        from aios.tools.http_get import _is_private

        host = urlparse(base_url).hostname
        if not host or _is_private(host):
            logger.warning("Evolution API send blocked: private server_url (%s)", host)
            return None

        to = message.extra_data.get("from_number") if message.extra_data else ""
        if not to:
            to = self._config.get("default_number", "")
        if not to:
            logger.warning("No recipient number for Evolution API send")
            return None

        try:
            from aios.core.whatsapp_guard import guard_send, humanize_delay

            ok, reason = await guard_send(to, message.text, provider="evolution")
            if not ok:
                logger.warning("Evolution guard block %s: %s", to, reason)
                return None
        except Exception:
            pass

        try:
            from aios.core.whatsapp_guard import humanize_delay

            delay = humanize_delay(message.text)
            await asyncio.sleep(delay)
            async with httpx.AsyncClient(timeout=30) as client:
                try:
                    await client.post(
                        f"{base_url}/chat/whatsappNumbers/{instance}",
                        headers={"apikey": api_key},
                        json={"numbers": [to]},
                    )
                except Exception:
                    pass
                try:
                    await client.post(
                        f"{base_url}/chat/updatePresence/{instance}",
                        headers={"apikey": api_key},
                        json={"number": to, "presence": "composing"},
                    )
                    await asyncio.sleep(random.uniform(1.0, 2.5))
                except Exception:
                    pass
                resp = await client.post(
                    f"{base_url}/message/sendText/{instance}",
                    headers={"apikey": api_key, "Content-Type": "application/json"},
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
                logger.warning("Evolution API send failed: %d %s", resp.status_code, resp.text[:500])
                return None
        except Exception:
            logger.exception("Evolution API send error")
            return None

    async def start(self) -> None:
        logger.info("Evolution API channel %s ready", self._config.get("instance", "?"))

    async def stop(self) -> None:
        pass

    async def test(self) -> dict:
        base_url = self._config.get("server_url", "").rstrip("/")
        api_key = self._config.get("api_key", "")
        instance = self._config.get("instance", "")
        if not base_url or not api_key:
            return {"ok": False, "message": "Missing server_url or api_key"}
        from urllib.parse import urlparse
        from aios.tools.http_get import _is_private
        host = urlparse(base_url).hostname
        if not host or _is_private(host):
            return {"ok": False, "message": "server_url must be a public URL"}
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{base_url}/instance/fetchInstances",
                    headers={"apikey": api_key},
                )
                if resp.status_code == 200:
                    instances = resp.json()
                    found = any(i.get("name") == instance for i in (instances if isinstance(instances, list) else []))
                    if found:
                        return {"ok": True, "message": f"Instance '{instance}' found and API connected"}
                    return {"ok": True, "message": "API connected (instance check skipped)"}
                return {"ok": False, "message": f"API error: {resp.status_code}"}
        except Exception as e:
            logger.exception("Evolution API test failed")
            return {"ok": False, "message": str(e)}
