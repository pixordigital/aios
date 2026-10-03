import logging
import httpx
import ipaddress
from aios.config import settings

logger = logging.getLogger(__name__)

def _evo_headers():
    # Fail closed: the old fallback to the public repo default meant any
    # install without a configured key authenticated as everyone else.
    # Empty key -> Evolution answers 401 -> every caller already handles that.
    key = settings.evolution_api_key or ""
    if not key:
        logger.error("EVOLUTION_API_KEY unset; Evolution calls will be rejected")
    return {"apikey": key, "Content-Type": "application/json"}

def _base() -> str:
    return (settings.evolution_server_url or "http://evolution:8080").rstrip("/")

def _get_ip_allowlist() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse comma-separated IP allowlist from settings."""
    if not settings.evolution_ip_allowlist:
        return []
    networks = []
    for part in settings.evolution_ip_allowlist.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            logger.warning("Invalid CIDR in evolution_ip_allowlist: %s", part)
    return networks

def check_evolution_ip_allowed(client_ip: str) -> bool:
    """Check if client IP is in the Evolution API allowlist."""
    allowlist = _get_ip_allowlist()
    if not allowlist:
        return True  # no allowlist configured = allow all
    try:
        client_addr = ipaddress.ip_address(client_ip)
        return any(client_addr in net for net in allowlist)
    except ValueError:
        return False

def get_evolution_key_rotation_status() -> dict:
    """Get Evolution API key rotation status."""
    rotation_days = settings.evolution_api_key_rotation_days or 30
    # This would ideally check a stored rotation timestamp
    # For now, return config info
    return {
        "rotation_days": rotation_days,
        "key_configured": bool(settings.evolution_api_key and settings.evolution_api_key != "evolution_secret_change_me"),
        "recommendation": f"Rotate Evolution API key every {rotation_days} days"
    }

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

async def evo_set_webhook(name: str, api_key: str = "") -> dict:
    """Point an instance's webhook at AIOS, with the shared secret.

    The shape here is verified against the running `evoapicloud/evolution-api:v2.3.7`:
    `POST /webhook/set/{instance}` validates a body with a required top-level
    `webhook` object (`enabled`, `url` required; `byEvents`, `base64`,
    `events`, `headers` optional) and answers 400 on anything else. A flat body
    is rejected outright.

    Two things this had to get right, and did not:

    * The secret goes in the custom `headers` map, not a `webhookAuth` field.
      Evolution accepts `webhookAuth`, never persists it, and then sends
      nothing — so every inbound call failed `_verify_request`.
    * The option keys are `byEvents` and `base64`. The `webhookByEvents` /
      `webhookBase64` names in the previous body are not in the schema, so they
      were silently dropped and Evolution applied its own defaults.

    Both call sites (instance creation and the channel form) must come through
    here; they had drifted into two different bodies, one of them with no
    auth header at all.
    """
    url = f"{settings.evolution_webhook_base.rstrip('/')}/{name}"
    key = api_key or settings.evolution_api_key or ""
    if not key:
        logger.error(
            "evo_set_webhook: no API key for instance %s — inbound will fail auth", name
        )
    body = {
        "webhook": {
            "enabled": True,
            "url": url,
            "byEvents": False,
            "base64": False,
            "events": ["MESSAGES_UPSERT"],
            "headers": {"x-webhook-auth": key},
        }
    }
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{_base()}/webhook/set/{name}",
                headers={"apikey": key, "Content-Type": "application/json"},
                json=body,
            )
        if r.status_code in (200, 201):
            return {"ok": True, "url": url}
        return {"ok": False, "message": f"{r.status_code}: {r.text[:200]}"}
    except Exception as e:
        logger.exception("evo_set_webhook failed for %s", name)
        return {"ok": False, "message": str(e)}


async def evo_create_instance(name: str):
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{_base()}/instance/create", headers=_evo_headers(), json={"instanceName": name, "qrcode": True, "integration": "WHATSAPP-BAILEYS"})
            data = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
            ok = r.status_code in (200, 201)
            if ok:
                # An instance with no webhook pointed at AIOS can send but
                # never receives, so it looked provisioned while being inert.
                hooked = await evo_set_webhook(name)
                if not hooked.get("ok"):
                    logger.error(
                        "Instance %s created but webhook not set: %s",
                        name, hooked.get("message"),
                    )
                    return {
                        "status": r.status_code, "data": data, "ok": True,
                        "webhook_ok": False, "webhook_error": hooked.get("message"),
                    }
            return {"status": r.status_code, "data": data, "ok": ok, "webhook_ok": True}
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


async def evo_send_text(instance: str, to: str, text: str) -> dict:
    """C4: Envia texto simples via Evolution Baileys."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{_base()}/message/sendText/{instance}",
                headers=_evo_headers(),
                json={"number": to, "textMessage": {"text": text}},
            )
            if r.status_code in (200, 201):
                return {"ok": True, "data": r.json()}
            return {"ok": False, "status": r.status_code, "error": r.text[:500]}
    except Exception as e:
        return {"ok": False, "error": str(e)}
