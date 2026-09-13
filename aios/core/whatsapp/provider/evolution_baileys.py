import httpx, logging
from aios.config import settings as global_settings
from .base import WhatsAppProvider, OutboundMessage, SendResult, HealthStatus

logger = logging.getLogger(__name__)

def _base(): return (global_settings.evolution_server_url or "http://evolution:8080").rstrip("/")
def _headers(): return {"apikey": global_settings.evolution_api_key or "evolution_secret_change_me", "Content-Type": "application/json"}

class EvolutionBaileysProvider(WhatsAppProvider):
    provider_type = "baileys"  # type: ignore
    async def send(self, instance: str, msg: OutboundMessage) -> SendResult:
        url = f"{_base()}/message/sendText/{instance}"
        payload = {"number": msg.to, "textMessage": {"text": msg.text or ""}}
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(url, headers=_headers(), json=payload)
                if r.status_code in (200,201):
                    d = r.json() if "application/json" in r.headers.get("content-type","") else {}
                    mid = d.get("key",{}).get("id") if isinstance(d.get("key"),dict) else d.get("id")
                    return SendResult(ok=True, message_id=mid, status_code=r.status_code)
                return SendResult(ok=False, error=r.text[:500], status_code=r.status_code)
        except Exception as e:
            return SendResult(ok=False, error=str(e))
    async def health(self, instance: str) -> HealthStatus:
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(f"{_base()}/instance/connectionState/{instance}", headers=_headers())
                d = r.json() if r.status_code==200 else {}
                state = d.get("state") or d.get("instance",{}).get("state") or ""
                connected = state in ("open","connected")
                return HealthStatus(connected=connected, provider="baileys")
        except Exception:
            return HealthStatus(connected=False, provider="baileys")
    async def create_instance(self, name: str) -> dict:
        from aios.core.evolution_api import evo_create_instance
        return await evo_create_instance(name)
    async def delete_instance(self, name: str) -> dict:
        from aios.core.evolution_api import evo_delete
        return await evo_delete(name)
