"""Rotas de integração ARVO ↔ AIOS (Fase 1C/2 + Fase payload + Fase persist). HMAC + in-memory + DB fallback."""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from aios.config import settings
from .auth import _forget_nonce, verification_keys, verify_request
from .events import ArvoEnvelope as ArvoEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations/arvo/v1", tags=["arvo-integration"])

# in-memory idempotency (fast) + DB persist (survive restart) — Fase 1-persist
_events: dict[str, tuple[float, dict]] = {}
_events_lock = threading.Lock()
_EVENTS_TTL = 86400
# Claim covers only pre-side-effect window (503 <=60s); handlers commit their done marker with the side effect for _EVENTS_TTL.
_PROCESSING_TTL = 60

# Fail-closed: only events with a handler may be claimed/deduplicated.
_ALLOWED_INBOUND_EVENTS = {
    "commitment.at_risk",
    "action.executed",
    "action.verified",
    "deal.created",
    "deal.stage_changed",
}


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


async def _db_mark_done_in_session(s, key: str, response: dict) -> None:
    """Mark event done inside the caller's side-effect transaction; caller commits."""
    from aios.db.models import IntegrationEvent

    with s.no_autoflush:  # marker read must not flush side effects before caller's commit
        row = await s.get(IntegrationEvent, key)
    if row:
        row.response = response
        row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=_EVENTS_TTL)


async def _db_release_event(key: str) -> None:
    from aios.db.engine import async_session
    from aios.db.models import IntegrationEvent

    async with async_session() as s:
        row = await s.get(IntegrationEvent, key)
        if row and row.response.get("status") == "processing":
            await s.delete(row)
            await s.commit()


class ContextRequest(BaseModel):
    business_trace_id: str | None = Field(default=None, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    org_id: str | None = None


class SsoTicketRequest(BaseModel):
    sub: str = Field(..., min_length=1, max_length=64)
    email: str = Field(..., min_length=1, max_length=255)
    org_id: str = Field(..., min_length=1, max_length=64)
    role: str = Field(..., min_length=1, max_length=50)


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


def _require_org_allowed(org_id: str | None) -> None:
    """Deny org outside AIOS_ARVO_ALLOWED_ORGS; empty CSV = unrestricted."""
    allowed = {v.strip() for v in (settings.arvo_allowed_orgs or "").split(",") if v.strip()}
    if allowed and str(org_id or "") not in allowed:
        raise HTTPException(403, "ARVO org not allowed")


async def _require_auth(request: Request) -> None:
    _require_enabled()
    if not settings.arvo_service_key or not settings.arvo_service_key_id:
        raise HTTPException(503, "ARVO integration not configured")
    kid = request.headers.get("x-service-key-id")
    ts = request.headers.get("x-service-timestamp")
    nonce = request.headers.get("x-service-nonce")
    sig = request.headers.get("x-service-signature")
    # Spelled as `or` rather than `all([...])` so the type checker narrows
    # each header to str; all() does not narrow, and verify_request must not
    # receive None.
    if not kid or not ts or not nonce or not sig:
        raise HTTPException(401, "Missing service signature")
    keys = verification_keys(settings.arvo_service_key_id, settings.arvo_service_key, settings.arvo_service_keys, kid)
    if not keys:
        raise HTTPException(401, "Unknown service key id")
    body = await request.body()
    for key in keys:
        if verify_request(
            kid, ts, nonce, request.method, request.url.path, body or None, sig, key,
            query=request.url.query, idempotency_key=request.headers.get("Idempotency-Key") or "",
        ):
            break
    else:
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
    _require_org_allowed(body.org_id)
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


@router.get("/deals", dependencies=[Depends(_require_auth)])
async def list_deals(request: Request, org_id: str | None = None, limit: int = 100):
    """Expose AIOS CRM deals to ARVO (single source of truth).

    Service-to-service, org-scoped. ARVO consumes this to detect leaks
    (stalled deals, discount exposure, overdue commitments) without owning
    a parallel CRM. org_id is required for any data; without it returns [].
    """
    _require_org_allowed(org_id)
    if not org_id:
        return {"org_id": None, "deals": [], "count": 0}
    cap = max(1, min(int(limit or 100), 500))
    try:
        from aios.db.engine import async_session
        from aios.db.models import CrmDeal
        from sqlalchemy import select

        async with async_session() as s:
            q = await s.execute(
                select(CrmDeal).where(CrmDeal.org_id == org_id).order_by(CrmDeal.created_at.desc()).limit(cap)
            )
            rows = q.scalars().all()
            deals = [
                {
                    "id": d.id,
                    "org_id": d.org_id,
                    "lead_name": d.lead_name,
                    "lead_email": d.lead_email,
                    "lead_phone": d.lead_phone,
                    "stage": d.stage,
                    "value": d.value,
                    "currency": d.currency,
                    "score": d.score,
                    "source": d.source,
                    "pipeline": d.pipeline,
                    "close_date": d.close_date.isoformat() if d.close_date else None,
                    "probability": d.probability,
                    "agent_id": d.agent_id,
                    "team_id": d.team_id,
                    "extra_data": d.extra_data or {},
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                    "updated_at": d.updated_at.isoformat() if d.updated_at else None,
                }
                for d in rows
            ]
            return {"org_id": org_id, "deals": deals, "count": len(deals)}
    except Exception as e:
        logger.debug("list_deals DB fallback: %s", e)
        return {"org_id": org_id, "deals": [], "count": 0, "error": str(e)[:200]}


async def _handle_action_executed(payload: dict, trace_id: str | None, idempotency_key: str, response: dict | None = None) -> dict:
    """ARVO action executed -> audit + (optional) deal stage nudge."""
    org_id = payload.get("org_id")
    action_id = payload.get("action_id") or payload.get("id") or "unknown"
    finding_id = payload.get("finding_id")
    trace_id = trace_id or payload.get("business_trace_id") or str(action_id)
    extra_resp = {"handled": "action.executed", "action_id": str(action_id), "business_trace_id": trace_id}
    if response is not None:
        response.update(extra_resp)
    try:
        if org_id:
            from aios.db.engine import async_session
            from aios.db.models import AuditLog

            async with async_session() as s:
                s.add(AuditLog(org_id=org_id, action="action.executed", resource_type="arvo_action",
                               resource_id=str(action_id), details={"finding_id": finding_id, "payload": payload}))
                if response is not None:
                    await _db_mark_done_in_session(s, idempotency_key, response)
                await s.commit()
    except Exception as e:
        logger.error("action.executed audit failed: %s", e)
        raise
    return extra_resp


async def _handle_action_verified(payload: dict, trace_id: str | None, idempotency_key: str, response: dict | None = None) -> dict:
    """ARVO verified recovery -> audit + update CrmDeal if deal_id provided."""
    org_id = payload.get("org_id")
    action_id = payload.get("action_id") or "unknown"
    finding_id = payload.get("finding_id")
    verified = payload.get("verified_amount")
    deal_id = payload.get("deal_id")
    trace_id = trace_id or payload.get("business_trace_id") or str(action_id)
    recovered = False
    if verified is not None:
        try:
            recovered = Decimal(str(verified)) > 0
        except (InvalidOperation, ValueError):
            recovered = False
    updated_deal = False
    extra_resp = {"handled": "action.verified", "action_id": str(action_id),
                  "verified_amount": verified, "deal_updated": updated_deal,
                  "business_trace_id": trace_id}
    if response is not None:
        response.update(extra_resp)
    try:
        if org_id:
            from aios.db.engine import async_session
            from aios.db.models import AuditLog, CrmDeal

            details = {"finding_id": finding_id, "verified_amount": verified, "deal_id": deal_id}
            if not recovered:
                details["recovery_verified"] = False
            async with async_session() as s:
                if deal_id and recovered:
                    deal = await s.get(CrmDeal, deal_id)
                    if deal and deal.org_id == org_id:
                        deal.stage = "closed_won"
                        deal.extra_data = {**(deal.extra_data or {}), "recovered_brl": verified}
                        updated_deal = True
                    elif deal:
                        details["deal_org_mismatch"] = True
                s.add(AuditLog(org_id=org_id, action="action.verified", resource_type="arvo_action",
                               resource_id=str(action_id), details=details))
                extra_resp["deal_updated"] = updated_deal
                if response is not None:
                    response.update(extra_resp)
                    await _db_mark_done_in_session(s, idempotency_key, response)
                await s.commit()
    except Exception as e:
        logger.error("action.verified audit/update failed: %s", e)
        raise
    return extra_resp


async def _handle_deal_event(payload: dict, trace_id: str | None, idempotency_key: str, action: str, response: dict | None = None) -> dict:
    org_id = payload.get("org_id")
    deal_id = payload.get("deal_id") or payload.get("id") or "unknown"
    trace_id = trace_id or payload.get("business_trace_id") or str(deal_id)
    extra_resp = {"handled": action, "deal_id": str(deal_id), "business_trace_id": trace_id}
    if response is not None:
        response.update(extra_resp)
    try:
        if org_id:
            from aios.db.engine import async_session
            from aios.db.models import AuditLog

            async with async_session() as s:
                s.add(AuditLog(org_id=org_id, action=action, resource_type="crm_deal",
                               resource_id=str(deal_id), details={"payload": payload}))
                if response is not None:
                    await _db_mark_done_in_session(s, idempotency_key, response)
                await s.commit()
    except Exception as e:
        logger.error("%s audit failed: %s", action, e)
        raise
    return extra_resp


async def _handle_commitment_at_risk(
    payload: dict,
    trace_id: str | None,
    idempotency_key: str,
    enqueue_succeeded: list[bool],
    response: dict | None = None,
) -> dict:
    """Phase 4 slice: commitment.at_risk → enqueue agent run → audit → outbox agent.action.completed."""
    finding_id = payload.get("finding_id") or payload.get("opportunity_id") or payload.get("id") or "unknown"
    trace_id = trace_id or payload.get("business_trace_id") or str(finding_id)
    extra = {"finding_id": finding_id, "business_trace_id": trace_id, "payload": payload}
    # Enqueue first: audit must not survive a queue failure, otherwise retry
    # (idempotency released) duplicates the row.
    # Residual: audit failure after enqueue leaves claim 503 for <=60s; later retry may re-enqueue but _job_id dedupes.
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
        # Tell caller before audit: audit failure must not release idempotency.
        enqueue_succeeded.append(True)
    except Exception:
        logger.debug("commitment.at_risk queue unavailable", exc_info=True)
    if not enqueued:
        return {"handled": "commitment.at_risk", "finding_id": str(finding_id), "business_trace_id": trace_id, "enqueued": False}
    success_resp = {"handled": "commitment.at_risk", "finding_id": str(finding_id),
                    "business_trace_id": trace_id, "enqueued": True}
    org_id = payload.get("org_id")
    if org_id:
        from aios.db.engine import async_session
        from aios.db.models import AuditLog

        try:
            async with async_session() as s:
                s.add(AuditLog(org_id=org_id, action="commitment.at_risk", resource_type="finding", resource_id=str(finding_id), details=extra))
                if response is not None:
                    response.update(success_resp)
                    await _db_mark_done_in_session(s, idempotency_key, response)
                await s.commit()
        except Exception as e:
            logger.error("commitment.at_risk audit failed: %s", e)
            raise
    else:
        logger.info("commitment.at_risk trace %s finding %s (no org_id, skip audit)", trace_id, finding_id)
        if response is not None:
            response.update(success_resp)
    return success_resp


@router.post("/events", dependencies=[Depends(_require_auth)])
async def ingest_event(
    body: ArvoEvent,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    _require_org_allowed(body.payload.get("org_id"))
    if body.type not in _ALLOWED_INBOUND_EVENTS:
        raise HTTPException(400, f"Unknown event type: {body.type}")
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
    enqueue_succeeded: list[bool] = []
    resp_base = {
        "status": "processed",
        "idempotency_key": idempotency_key,
        "type": body.type,
        "business_trace_id": trace_id,
        "event_version": body.event_version or "1",
    }
    try:
        extra_resp: dict = {}
        if body.type == "commitment.at_risk":
            extra_resp = await _handle_commitment_at_risk(
                body.payload,
                trace_id,
                idempotency_key,
                enqueue_succeeded,
                resp_base,
            )
            if not extra_resp.get("enqueued"):
                raise HTTPException(503, "ARVO integration queue unavailable")
            side_effect_started = True
        elif body.type == "action.executed":
            extra_resp = await _handle_action_executed(body.payload, trace_id, idempotency_key, resp_base)
            side_effect_started = True
        elif body.type == "action.verified":
            extra_resp = await _handle_action_verified(body.payload, trace_id, idempotency_key, resp_base)
            side_effect_started = True
        elif body.type == "deal.created":
            extra_resp = await _handle_deal_event(body.payload, trace_id, idempotency_key, "deal.created", resp_base)
            side_effect_started = True
        elif body.type == "deal.stage_changed":
            extra_resp = await _handle_deal_event(body.payload, trace_id, idempotency_key, "deal.stage_changed", resp_base)
            side_effect_started = True
        resp = {**resp_base, "deduplicated": False, **extra_resp}
        stripped = {k: v for k, v in resp.items() if k != "deduplicated"}
        await _db_complete_event(idempotency_key, stripped)
        _store_idempotent(idempotency_key, stripped)
        return resp
    except Exception:
        if not side_effect_started and not enqueue_succeeded:
            await _db_release_event(idempotency_key)
        elif side_effect_started:
            # Marker committed with the side effect is DB authority; cache it here too.
            _store_idempotent(idempotency_key, resp_base)
        raise

@router.post("/sso-ticket", dependencies=[Depends(_require_auth)])
async def sso_ticket(identity: SsoTicketRequest):
    """Signed SSO ticket carrying asserted user identity, TTL <= 60s."""
    _require_org_allowed(identity.org_id)
    import json
    import hmac
    import hashlib
    import secrets
    import jwt
    from .auth import _PATH

    key_id = settings.arvo_service_key_id
    key = settings.arvo_service_key

    if not key or not key_id:
        raise HTTPException(503, "ARVO integration not configured")

    ts = str(int(time.time()))
    nonce = secrets.token_hex(32)
    persisted = await _db_persist_nonce(nonce)
    if persisted is False:
        raise HTTPException(401, "Replay nonce (SSO ticket)")
    if persisted is None:
        raise HTTPException(503, "Replay protection unavailable")

    iat = int(ts)
    payload = {
        "iss": "aios",
        "aud": "arvo",
        "iat": iat,
        "exp": iat + 60,
        "jti": nonce,
        "sub": identity.sub,
        "email": identity.email,
        "org_id": identity.org_id,
        "role": identity.role,
    }
    bhash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    canonical = f"{key_id}.{ts}.{nonce}.POST.{_PATH}.{bhash}"
    sig = hmac.new(key.encode(), canonical.encode(), hashlib.sha256).hexdigest()

    return {
        "ticket": jwt.encode(payload, key, algorithm="HS256"),
        "key_id": key_id,
        "timestamp": ts,
        "nonce": nonce,
        "signature": sig,
        "expires_in": 60,
    }
