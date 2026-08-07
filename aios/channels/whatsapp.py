"""WhatsApp Cloud API channel - webhook receiver + outbound."""

import logging

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
        import httpx
        token = self._config.get("access_token", "")
        phone_id = self._config.get("phone_id", "")
        to = message.extra_data.get("from_number") if message.extra_data else ""
        if not token or not phone_id or not to:
            logger.warning("WhatsApp send incomplete: token=%s phone=%s to=%s", bool(token), bool(phone_id), to)
            return None
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://graph.facebook.com/v18.0/{phone_id}/messages",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "text",
                    "text": {"body": message.text},
                },
            )
            data = resp.json()
            return (data.get("messages") or [{}])[0].get("id")

    async def _zernio_send(self, message: OutboundMessage) -> str | None:
        """WhatsApp via Zernio — unified REST API. Bearer-key auth, fixed host."""
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
                    # freeform reply inside an open thread
                    resp = await client.post(
                        f"{base}/inbox/conversations/{conversation_id}/messages",
                        headers=headers,
                        json={"accountId": account_id, "message": message.text},
                    )
                else:
                    if not to:
                        logger.warning("Zernio cold outreach missing recipient number")
                        return None
                    # cold outreach: open a new conversation — WhatsApp requires a template
                    template_name = self._config.get("template_name", "")
                    if template_name:
                        payload = {
                            "accountId": account_id,
                            "participantId": to,
                            "templateName": template_name,
                            "templateLanguage": self._config.get("template_language", "en_US"),
                            "templateParams": self._config.get("template_params_default", []),
                        }
                    else:
                        # no approved template: utility/Direct Send freeform
                        payload = {
                            "accountId": account_id,
                            "participantId": to,
                            "message": message.text,
                            "category": "utility",
                        }
                    resp = await client.post(
                        f"{base}/inbox/conversations",
                        headers=headers,
                        json=payload,
                    )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    # Zernio returns the created conversation on cold outreach, message on reply
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
                    resp = await client.get(
                        "https://zernio.com/api/v1/auth/verify",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    data = resp.json()
                    if resp.status_code == 200 and data.get("valid"):
                        return {"ok": True, "message": "Zernio API key valid"}
                    return {"ok": False, "message": f"Zernio API error: {data.get('error', resp.status_code)}"}
            except Exception as e:
                logger.exception("Zernio test failed")
                return {"ok": False, "message": str(e)}
        import httpx
        token = self._config.get("access_token", "")
        phone_id = self._config.get("phone_id", "")
        if not token or not phone_id:
            return {"ok": False, "message": "Missing access_token or phone_id"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://graph.facebook.com/v18.0/{phone_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code == 200:
                    return {"ok": True, "message": f"WhatsApp API connected — {resp.json().get('display_phone_numbers', [{}])[0].get('verified_name', 'ok')}"}
                return {"ok": False, "message": f"API error: {resp.status_code}"}
        except Exception as e:
            logger.exception("WhatsApp API test failed")
            return {"ok": False, "message": str(e)}
