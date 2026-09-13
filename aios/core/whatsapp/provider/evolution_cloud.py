import httpx, logging
from aios.config import settings as global_settings
from .base import WhatsAppProvider, OutboundMessage, SendResult, HealthStatus

logger = logging.getLogger(__name__)

def _base(): return (global_settings.evolution_server_url or "http://evolution:8080").rstrip("/")
def _headers(): return {"apikey": global_settings.evolution_api_key or "evolution_secret_change_me", "Content-Type": "application/json"}

class EvolutionCloudProvider(WhatsAppProvider):
    provider_type = "cloud"  # type: ignore
    async def send(self, instance: str, msg: OutboundMessage) -> SendResult:
        # Cloud API via Evolution: /message/sendWhatsApp/{instance}
        url = f"{_base()}/message/sendWhatsApp/{instance}"
        if msg.template:
            payload = {"number": msg.to, "type": "template", "template": msg.template}
        else:
            payload = {"number": msg.to, "type": "text", "text": msg.text or ""}
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(url, headers=_headers(), json=payload)
                if r.status_code in (200,201):
                    d = r.json() if "application/json" in r.headers.get("content-type","") else {}
                    return SendResult(ok=True, message_id=d.get("messages",[{}])[0].get("id") if d.get("messages") else d.get("id"), status_code=r.status_code)
                return SendResult(ok=False, error=r.text[:500], status_code=r.status_code)
        except Exception as e:
            return SendResult(ok=False, error=str(e))
    async def health(self, instance: str) -> HealthStatus:
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(f"{_base()}/instance/connectionState/{instance}", headers=_headers())
                d = r.json() if r.status_code==200 else {}
                state = d.get("state") or ""
                connected = state in ("open","connected")
                return HealthStatus(connected=connected, provider="cloud")
        except Exception:
            return HealthStatus(connected=False, provider="cloud")
    async def create_instance(self, name: str) -> dict:
        # Cloud API instance creation differs: integration=WHATSAPP-CLOUD
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(f"{_base()}/instance/create", headers=_headers(), json={"instanceName": name, "integration": "WHATSAPP-CLOUD"})
                return {"ok": r.status_code in (200,201), "status": r.status_code, "data": r.json() if "application/json" in r.headers.get("content-type","") else {}}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    async def delete_instance(self, name: str) -> dict:
        from aios.core.evolution_api import evo_delete
        return await evo_delete(name)
