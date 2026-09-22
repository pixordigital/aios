"""Rotas de integração ARVO ↔ AIOS (Fase 1C/2). Feature-gated + HMAC."""

from fastapi import APIRouter, Depends, HTTPException, Request

from aios.config import settings
from .auth import verify_request

router = APIRouter(prefix="/api/integrations/arvo/v1", tags=["arvo-integration"])


def _require_enabled() -> None:
    if not settings.arvo_integration_enabled:
        raise HTTPException(404, "ARVO integration disabled")


async def _require_auth(request: Request) -> None:
    _require_enabled()
    if not settings.arvo_service_key or not settings.arvo_service_key_id:
        raise HTTPException(503, "ARVO integration not configured")
    kid = request.headers.get("x-service-key-id")
    ts = request.headers.get("x-service-timestamp")
    nonce = request.headers.get("x-service-nonce")
    sig = request.headers.get("x-service-signature")
    if not all([kid, ts, nonce, sig]):
        raise HTTPException(401, "Missing service signature")
    if kid != settings.arvo_service_key_id:
        raise HTTPException(401, "Unknown service key id")
    body = await request.body()
    if not verify_request(kid, ts, nonce, request.method, request.url.path, body or None, sig, settings.arvo_service_key):
        raise HTTPException(401, "Invalid service signature")


@router.get("/health", dependencies=[Depends(_require_auth)])
async def health():
    return {"status": "ok", "service": "aios", "peer": "arvo"}


@router.post("/health", dependencies=[Depends(_require_auth)])
async def health_probe():
    return await health()
