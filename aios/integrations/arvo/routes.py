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
    business_trace_id: str | None = Field(default=None, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    event_version: str | None = Field(default="1", max_length=16)


class ContextRequest(BaseModel):
    business_trace_id: str | None = Field(default=None, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    org_id: str | None = None


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


@router.post("/context", dependencies=[Depends(_require_auth)])
async def get_context(body: ContextRequest):
    """Phase 2 — minimal agent-context per contract. No org leak if unknown."""
    # ponytail: minimal context, reuse existing agents table if org_id provided
    agents_info: list[dict] = []
    plan = "free"
    if body.org_id:
        try:
            from aios.db.engine import async_session
            from aios.db.models import Agent, Organization
            from sqlalchemy import select

            async with async_session() as s:
                org = await s.get(Organization, body.org_id)
                if org and isinstance(org.extra_data, dict):
                    plan = org.extra_data.get("plan", "free")
                q = await s.execute(select(Agent).where(Agent.org_id == body.org_id).limit(10))
                for ag in q.scalars().all():
                    agents_info.append({"id": ag.id, "name": ag.name, "type": ag.agent_type})
        except Exception as e:
            logger.debug("context DB fallback: %s", e)
    return {"org_id": body.org_id, "plan": plan, "agents": agents_info, "business_trace_id": body.business_trace_id, "event_version": "1"}


async def _handle_commitment_at_risk(payload: dict, trace_id: str | None) -> dict:
    """Phase 4 slice: commitment.at_risk → cria pending audit log + tenta notificar. Minimal, não bloqueia."""
    finding_id = payload.get("finding_id") or payload.get("opportunity_id") or payload.get("id") or "unknown"
    extra = {"finding_id": finding_id, "business_trace_id": trace_id, "payload": payload}
    try:
        org_id = payload.get("org_id")
        if org_id:
            from aios.db.engine import async_session
            from aios.db.models import AuditLog

            async with async_session() as s:
                s.add(AuditLog(org_id=org_id, action="commitment.at_risk", resource_type="finding", resource_id=str(finding_id), details=extra))
                await s.commit()
        else:
            logger.info("commitment.at_risk trace %s finding %s (no org_id, skip audit)", trace_id, finding_id)
    except Exception as e:
        logger.debug("commitment.at_risk audit fallback: %s", e)
    # ponytail: no auto-execution, just ACK; caller (ARVO) drives next step via agent.action.completed
    return {"handled": "commitment.at_risk", "finding_id": str(finding_id), "business_trace_id": trace_id}


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
    # Phase 4: vertical slice handler
    trace_id = body.business_trace_id or body.payload.get("business_trace_id")
    extra_resp: dict = {}
    if body.type == "commitment.at_risk":
        extra_resp = await _handle_commitment_at_risk(body.payload, trace_id)
    # Phase 5: echo trace
    resp = {"status": "processed", "idempotency_key": idempotency_key, "type": body.type, "business_trace_id": trace_id, "event_version": body.event_version or "1", "deduplicated": False, **extra_resp}
    stripped = {k: v for k, v in resp.items() if k != "deduplicated"}
    _store_idempotent(idempotency_key, stripped)
    await _db_store_event(idempotency_key, body.type, {**body.payload, "business_trace_id": trace_id} if trace_id else body.payload, stripped)
    return resp
