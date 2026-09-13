import httpx, logging
from aios.config import settings as global_settings
from .base import WhatsAppProvider, OutboundMessage, SendResult, HealthStatus

logger = logging.getLogger(__name__)

def _base(): return (global_settings.evolution_server_url or "http://evolution:8080").rstrip("/")
def _headers(): return {"apikey": global_settings.evolution_api_key or "evolution_secret_change_me", "Content-Type": "application/json"}

class EvolutionCoexistenceProvider(WhatsAppProvider):
    provider_type = "coexistence"  # type: ignore
    # Send = Cloud API mesmo endpoint, mas is_on_biz_app=true
    async def send(self, instance: str, msg: OutboundMessage) -> SendResult:
        url = f"{_base()}/message/sendWhatsApp/{instance}"
        payload = {"number": msg.to, "type": "template" if msg.template else "text", "template": msg.template} if msg.template else {"number": msg.to, "text": msg.text or ""}
        # Cloud coexistence usa mesmo endpoint Cloud
        if not msg.template:
            payload = {"number": msg.to, "type": "text", "text": msg.text or ""}
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(url, headers=_headers(), json=payload)
                if r.status_code in (200,201):
                    d = r.json() if "application/json" in r.headers.get("content-type","") else {}
                    mid = d.get("messages",[{}])[0].get("id") if d.get("messages") else d.get("id")
                    return SendResult(ok=True, message_id=mid, status_code=r.status_code)
                return SendResult(ok=False, error=r.text[:500], status_code=r.status_code)
        except Exception as e:
            return SendResult(ok=False, error=str(e))

    async def health(self, instance: str) -> HealthStatus:
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(f"{_base()}/instance/fetchInstances", headers=_headers())
                if r.status_code==200:
                    for inst in r.json() if isinstance(r.json(), list) else []:
                        name = inst.get("name") or inst.get("instanceName") or inst.get("instance",{}).get("instanceName","")
                        if name==instance:
                            # coexistence flag
                            is_coex = inst.get("is_on_biz_app") or inst.get("isOnBizApp") or False
                            state = inst.get("state") or inst.get("instance",{}).get("state") or ""
                            connected = state in ("open","connected")
                            # risco ban ~0 para coexistence (Cloud oficial)
                            return HealthStatus(connected=connected, provider="coexistence", risk_score=5 if connected else 40)
                # fallback connectionState
                r2 = await c.get(f"{_base()}/instance/connectionState/{instance}", headers=_headers())
                d = r2.json() if r2.status_code==200 else {}
                state = d.get("state") or ""
                return HealthStatus(connected=state in ("open","connected"), provider="coexistence", risk_score=5 if state in ("open","connected") else 40)
        except Exception:
            return HealthStatus(connected=False, provider="coexistence", risk_score=40)

    async def create_instance(self, name: str) -> dict:
        # Coexistence requer Embedded Signup no frontend; backend cria placeholder Cloud
        # Meta cria WABA coexistence via Embedded Signup com appId configurado
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(f"{_base()}/instance/create", headers=_headers(), json={"instanceName": name, "integration": "WHATSAPP-CLOUD", "isOnBizApp": True})
                return {"ok": r.status_code in (200,201), "status": r.status_code, "data": r.json() if "application/json" in r.headers.get("content-type","") else {}, "coexistence": True}
        except Exception as e:
            return {"ok": False, "error": str(e), "coexistence": True}

    async def delete_instance(self, name: str) -> dict:
        from aios.core.evolution_api import evo_delete
        return await evo_delete(name)

    @staticmethod
    def is_smb_echo(webhook_body: dict) -> bool:
        # App → API espelhamento
        return "smb_message_echoes" in str(webhook_body) or webhook_body.get("event")=="smb_message_echoes"
