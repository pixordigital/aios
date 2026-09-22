"""Cliente HTTP para o peer ARVO (Fase 1D + payload). Assina requests via auth.sign_request."""

import json
import uuid

import httpx

from aios.config import settings
from .auth import sign_request

PATH_PREFIX = "/api/v1/integrations/aios/v1"


def _headers(method: str, path: str, body: bytes | None = None) -> dict[str, str]:
    return sign_request(
        method, path, body, settings.arvo_service_key_id, settings.arvo_service_key
    )


async def ping() -> dict:
    """GET /health do peer. Usa http:// pois certificado sslip/https 503 conhecido (GAPS §6)."""
    path = f"{PATH_PREFIX}/health"
    async with httpx.AsyncClient(base_url=settings.arvo_base_url) as c:
        r = await c.get(path, headers=_headers("GET", path))
        r.raise_for_status()
        return r.json()


async def send_event(event_type: str, payload: dict, idempotency_key: str | None = None) -> dict:
    """POST /events idempotente."""
    body_dict = {"type": event_type, "payload": payload}
    body = json.dumps(body_dict, separators=(",", ":")).encode()
    path = f"{PATH_PREFIX}/events"
    headers = _headers("POST", path, body)
    headers["Idempotency-Key"] = idempotency_key or str(uuid.uuid4())
    headers["Content-Type"] = "application/json"
    async with httpx.AsyncClient(base_url=settings.arvo_base_url) as c:
        r = await c.post(path, content=body, headers=headers)
        r.raise_for_status()
        return r.json()
