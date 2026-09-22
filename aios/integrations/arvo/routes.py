"""Rotas de integração ARVO ↔ AIOS (Fase 1C/2 + Fase payload + Fase persist). HMAC + in-memory + DB fallback."""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from aios.config import settings
from .auth import verify_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations/arvo/v1", tags=["arvo-integration"])

# in-memory idempotency (fast) + DB persist (survive restart) — Fase 1-persist
_events: dict[str, tuple[float, dict]] = {}
_events_lock = threading.Lock()
_EVENTS_TTL = 86400


async def _db_persist_nonce(nonce: str) -> bool:
    """Tenta inserir nonce no DB; False se duplicate. Fallback True se DB off."""
    try:
        from sqlalchemy import delete

        from aios.db.engine import async_session
        from aios.db.models import IntegrationNonce

        expires = datetime.now(timezone.utc) + timedelta(seconds=600)
        async with async_session() as s:
            await s.execute(delete(IntegrationNonce).where(IntegrationNonce.expires_at < datetime.now(timezone.utc)))
            s.add(IntegrationNonce(nonce=nonce, peer="arvo", expires_at=expires))
            await s.commit()
            return True
    except Exception as e:
        msg = str(e).lower()
        if "unique" in msg or "duplicate" in msg or "integrity" in msg:
            try:
                await s.rollback()  # type: ignore
            except Exception:
                pass
            return False
        logger.debug("nonce DB fallback (in-memory only): %s", e)
        return True


async def _db_get_event(key: str) -> dict | None:
    try:
        from aios.db.engine import async_session
        from aios.db.models import IntegrationEvent

        async with async_session() as s:
            obj = await s.get(IntegrationEvent, key)
            if obj and obj.expires_at > datetime.now(timezone.utc):
                return obj.response
            if obj and obj.expires_at <= datetime.now(timezone.utc):
                await s.delete(obj)
                await s.commit()
    except Exception as e:
        logger.debug("event DB get fallback: %s", e)
    return None


async def _db_store_event(key: str, type_: str, payload: dict, resp: dict) -> None:
    try:
        from aios.db.engine import async_session
        from aios.db.models import IntegrationEvent

        expires = datetime.now(timezone.utc) + timedelta(seconds=_EVENTS_TTL)
        async with async_session() as s:
            s.add(IntegrationEvent(idempotency_key=key, peer="arvo", type=type_, payload=payload, response=resp, expires_at=expires))
            await s.commit()
    except Exception as e:
        logger.debug("event DB store fallback: %s", e)


class ArvoEvent(BaseModel):
    type: str = Field(..., max_length=64, pattern=r"^[a-z0-9_.-]+$")
    payload: dict = Field(default_factory=dict)
    occurred_at: str | None = None


def _get_idempotent(key: str) -> dict | None:
    now = time.time()
    with _events_lock:
        for k, (exp, _) in list(_events.items()):
            if exp < now:
                del _events[k]
        if key in _events:
            return _events[key][1]
    return None


def _store_idempotent(key: str, resp: dict) -> None:
    with _events_lock:
        _events[key] = (time.time() + _EVENTS_TTL, resp)


def _clear_events() -> None:
    with _events_lock:
        _events.clear()


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
    # DB nonce dedup (survive restart) — fallback para in-memory se DB off
    if not await _db_persist_nonce(nonce):
        raise HTTPException(401, "Replay nonce (DB)")


@router.get("/health", dependencies=[Depends(_require_auth)])
async def health():
    return {"status": "ok", "service": "aios", "peer": "arvo"}


@router.post("/health", dependencies=[Depends(_require_auth)])
async def health_probe():
    return await health()


@router.post("/events", dependencies=[Depends(_require_auth)])
async def ingest_event(
    body: ArvoEvent,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(400, "Invalid Idempotency-Key")
    cached = _get_idempotent(idempotency_key)
    if cached is not None:
        return {**cached, "deduplicated": True}
    db_cached = await _db_get_event(idempotency_key)
    if db_cached is not None:
        _store_idempotent(idempotency_key, db_cached)
        return {**db_cached, "deduplicated": True}
    resp = {"status": "processed", "idempotency_key": idempotency_key, "type": body.type, "deduplicated": False}
    stripped = {k: v for k, v in resp.items() if k != "deduplicated"}
    _store_idempotent(idempotency_key, stripped)
    await _db_store_event(idempotency_key, body.type, body.payload, stripped)
    return resp
