"""Rotas de integração ARVO ↔ AIOS (Fase 1C/2 + Fase payload + Fase persist). HMAC + in-memory + DB fallback."""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from aios.config import settings
from .auth import _forget_nonce, verify_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations/arvo/v1", tags=["arvo-integration"])

# in-memory idempotency (fast) + DB persist (survive restart) — Fase 1-persist
_events: dict[str, tuple[float, dict]] = {}
_events_lock = threading.Lock()
_EVENTS_TTL = 86400
_PROCESSING_TTL = 60


async def _db_persist_nonce(nonce: str) -> bool | None:
    """Insert nonce; False means duplicate, None means persistence unavailable."""
    try:
        from sqlalchemy import delete

        from aios.db.engine import async_session
        from aios.db.models import IntegrationNonce

        expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=600)
        async with async_session() as s:
            await s.execute(delete(IntegrationNonce).where(IntegrationNonce.expires_at < datetime.now(timezone.utc).replace(tzinfo=None)))
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
        logger.error("nonce persistence unavailable: %s", e)
        return None


async def _db_get_event(key: str) -> dict | None:
    try:
        from aios.db.engine import async_session
        from aios.db.models import IntegrationEvent

        async with async_session() as s:
            obj = await s.get(IntegrationEvent, key)
            if obj and obj.expires_at > datetime.now(timezone.utc).replace(tzinfo=None):
                return obj.response
            if obj and obj.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None):
                await s.delete(obj)
                await s.commit()
    except Exception as e:
        logger.debug("event DB get fallback: %s", e)
    return None


async def _db_claim_event(key: str, type_: str, payload: dict) -> tuple[bool, dict | None]:
    from sqlalchemy.exc import IntegrityError

    from aios.db.engine import async_session
    from aios.db.models import IntegrationEvent

    expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=_PROCESSING_TTL)
    async with async_session() as s:
        existing = await s.get(IntegrationEvent, key)
        if existing and existing.expires_at > datetime.now(timezone.utc).replace(tzinfo=None):
            return False, existing.response
        if existing:
            await s.delete(existing)
            await s.flush()
        s.add(
            IntegrationEvent(
                idempotency_key=key,
                peer="arvo",
                type=type_,
                payload=payload,
                response={"status": "processing"},
                expires_at=expires,
            )
        )
        try:
            await s.commit()
            return True, None
        except IntegrityError:
            await s.rollback()
            existing = await s.get(IntegrationEvent, key)
            return False, existing.response if existing else None


async def _db_complete_event(key: str, response: dict) -> None:
    from aios.db.engine import async_session
    from aios.db.models import IntegrationEvent

    async with async_session() as s:
        row = await s.get(IntegrationEvent, key)
        if row:
            row.response = response
            row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=_EVENTS_TTL)
            await s.commit()


async def _db_release_event(key: str) -> None:
    from aios.db.engine import async_session
    from aios.db.models import IntegrationEvent

    async with async_session() as s:
        row = await s.get(IntegrationEvent, key)
        if row and row.response.get("status") == "processing":
            await s.delete(row)
            await s.commit()


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
    persisted = await _db_persist_nonce(nonce)
    if persisted is False:
        raise HTTPException(401, "Replay nonce (DB)")
    if persisted is None:
        _forget_nonce(nonce)
        raise HTTPException(503, "Replay protection unavailable")


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


async def _handle_commitment_at_risk(
    payload: dict,
    trace_id: str | None,
    idempotency_key: str,
) -> dict:
    """Phase 4 slice: commitment.at_risk → audit + enqueue agent run → outbox agent.action.completed."""
    finding_id = payload.get("finding_id") or payload.get("opportunity_id") or payload.get("id") or "unknown"
    trace_id = trace_id or payload.get("business_trace_id") or str(finding_id)
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
    # enqueue agent execution via ARQ (non-blocking) + inline fallback if no redis
    enqueued = False
    try:
        from aios.tasks.queue import enqueue_job
        await enqueue_job(
            "process_commitment_at_risk",
            payload=payload,
            business_trace_id=trace_id,
            _job_id=f"commitment:{idempotency_key}",
        )
        enqueued = True
    except Exception:
        logger.debug("commitment.at_risk queue unavailable; using background fallback", exc_info=True)
    return {"handled": "commitment.at_risk", "finding_id": str(finding_id), "business_trace_id": trace_id, "enqueued": enqueued}


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
        if db_cached.get("status") == "processing":
            raise HTTPException(503, "Event processing in progress")
        _store_idempotent(idempotency_key, db_cached)
        return {**db_cached, "deduplicated": True}
    trace_id = body.business_trace_id or body.payload.get("business_trace_id")
    event_payload = {**body.payload, "business_trace_id": trace_id} if trace_id else body.payload
    claimed, existing = await _db_claim_event(idempotency_key, body.type, event_payload)
    if not claimed:
        if existing is None:
            raise HTTPException(503, "Idempotency reservation unavailable")
        if existing.get("status") == "processing":
            raise HTTPException(503, "Event processing in progress")
        _store_idempotent(idempotency_key, existing)
        return {**existing, "deduplicated": True}
    side_effect_started = False
    try:
        extra_resp: dict = {}
        if body.type == "commitment.at_risk":
            extra_resp = await _handle_commitment_at_risk(
                body.payload,
                trace_id,
                idempotency_key,
            )
            if not extra_resp.get("enqueued"):
                raise HTTPException(503, "ARVO integration queue unavailable")
            side_effect_started = True
        resp = {
            "status": "processed",
            "idempotency_key": idempotency_key,
            "type": body.type,
            "business_trace_id": trace_id,
            "event_version": body.event_version or "1",
            "deduplicated": False,
            **extra_resp,
        }
        stripped = {k: v for k, v in resp.items() if k != "deduplicated"}
        await _db_complete_event(idempotency_key, stripped)
        _store_idempotent(idempotency_key, stripped)
        return resp
    except Exception:
        if not side_effect_started:
            await _db_release_event(idempotency_key)
        raise
