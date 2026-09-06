import logging
import httpx
from aios.config import settings

logger = logging.getLogger(__name__)

def _evo_headers():
    return {"apikey": settings.evolution_api_key or "evolution_secret_change_me", "Content-Type": "application/json"}

def _base() -> str:
    return (settings.evolution_server_url or "http://evolution:8080").rstrip("/")

async def evo_fetch_instances():
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{_base()}/instance/fetchInstances", headers=_evo_headers())
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning("evo fetch failed %s", e)
    return []

async def evo_create_instance(name: str):
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{_base()}/instance/create", headers=_evo_headers(), json={"instanceName": name, "qrcode": True, "integration": "WHATSAPP-BAILEYS"})
            data = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
            # set webhook to AIOS
            webhook_url = f"{settings.app_url.rstrip('/')}/api/evolution/webhook/{name}"
            try:
                await c.post(f"{_base()}/webhook/set/{name}", headers=_evo_headers(), json={"webhook": {"enabled": True, "url": webhook_url, "webhookByEvents": False, "webhookBase64": False, "events": ["MESSAGES_UPSERT"]}})
            except Exception:
                pass
            return {"status": r.status_code, "data": data, "ok": r.status_code in (200,201)}
    except Exception as e:
        return {"status": 0, "error": str(e), "ok": False}

async def evo_connect(name: str):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{_base()}/instance/connect/{name}", headers=_evo_headers())
            data = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
            return {"status": r.status_code, "data": data, "ok": r.status_code==200}
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def evo_status(name: str):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{_base()}/instance/connectionState/{name}", headers=_evo_headers())
            data = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
            return {"status": r.status_code, "data": data, "ok": r.status_code==200}
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def evo_logout(name: str):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.delete(f"{_base()}/instance/logout/{name}", headers=_evo_headers())
            return {"ok": r.status_code in (200,201), "status": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def evo_delete(name: str):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.delete(f"{_base()}/instance/delete/{name}", headers=_evo_headers())
            return {"ok": r.status_code in (200,201), "status": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def evo_restart(name: str):
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.put(f"{_base()}/instance/restart/{name}", headers=_evo_headers())
            return {"ok": r.status_code in (200,201), "status": r.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}
