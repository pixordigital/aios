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

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def test(self) -> dict:
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
