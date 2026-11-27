import hashlib
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel
from sqlalchemy import select

from aios.core.approval_evidence import verify_and_consume_approval

from .deps import get_current_user, get_org_id

logger = logging.getLogger(__name__)

_WHATSAPP_APPROVAL_TOOLS = {
    "send": "whatsapp_template",
    "call": "voice_call",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _approval_fingerprint(*, org_id: str, action: str, body: "SendBody | CallBody") -> str:
    if action == "send":
        assert isinstance(body, SendBody)
        payload = {
            "action": "send",
            "instance": body.instance,
            "to": body.to,
            "text": body.text,
            "provider": body.provider,
        }
        tool_name = _WHATSAPP_APPROVAL_TOOLS["send"]
    else:
        assert isinstance(body, CallBody)
        payload = {
            "action": "call",
            "instance": body.instance,
            "to": body.to,
            "script": body.script,
        }
        tool_name = _WHATSAPP_APPROVAL_TOOLS["call"]
    raw = _canonical_json({"org_id": org_id, "tool_name": tool_name, "payload": payload})
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _approval_args_match(*, action: str, body: "SendBody | CallBody", tool_args: Any) -> bool:
    if not isinstance(tool_args, dict):
        return False
    # Support explicit fingerprint marker for forward compat.
    marker = tool_args.get("_wa_approved_action")
    if isinstance(marker, dict):
        fp = str(marker.get("fingerprint") or "")
        if fp and fp == _approval_fingerprint(org_id=str(marker.get("org_id") or ""), action=action, body=body):
            # org_id in marker is informational; DB org binding is authoritative below.
            pass
        elif fp:
            return False
        marker_action = str(marker.get("action") or "")
        if marker_action and marker_action != action:
            return False
        marker_tool = str(marker.get("tool_name") or "")
        if marker_tool and marker_tool != _WHATSAPP_APPROVAL_TOOLS[action]:
            return False
    # Verify known args. Ignore internal metadata keys.
    if action == "send":
        assert isinstance(body, SendBody)
        expected = {
            "instance": body.instance,
            "to": body.to,
            "text": body.text,
            "provider": body.provider,
        }
    else:
        assert isinstance(body, CallBody)
        expected = {
            "instance": body.instance,
            "to": body.to,
            "script": body.script,
        }
    for k, v in expected.items():
        if k in tool_args and tool_args.get(k) != v:
            return False
    # If tool args include an explicit action/target, require match.
    if "action" in tool_args and str(tool_args.get("action")) != action:
        return False
    return True


async def _consume_whatsapp_approval(
    db,
    *,
    org_id: str,
    user,
    action: str,
    body: "SendBody | CallBody",
    approval_action_id: str | None,
) -> tuple[bool, str, dict[str, Any]]:
    expected_tool = _WHATSAPP_APPROVAL_TOOLS[action]
    result = await verify_and_consume_approval(
        db,
        org_id=str(org_id),
        approval_action_id=approval_action_id,
        expected_tool_name=expected_tool,
        args_match=lambda tool_args: _approval_args_match(action=action, body=body, tool_args=tool_args),
    )
    details = dict(result.details)
    if result.ok:
        details["approval_fingerprint"] = _approval_fingerprint(org_id=str(org_id), action=action, body=body)
    return result.ok, result.reason, details


async def _assert_whatsapp_instance_owned(db, *, org_id: str, user, instance: str, source: str) -> None:
    from sqlalchemy import select as sql_select

    from aios.db.models import ChannelConnection

    rows = (
        await db.execute(
            sql_select(ChannelConnection.config).where(
                ChannelConnection.org_id == org_id,
                ChannelConnection.channel_type == "evolution",
            )
        )
    ).all()
    if any((r[0] or {}).get("instance") == instance for r in rows):
        return
    try:
        other = (
            await db.execute(
                sql_select(ChannelConnection)
                .where(
                    ChannelConnection.channel_type == "evolution",
                    ChannelConnection.org_id != org_id,
                    ChannelConnection.config["instance"].as_string() == instance,
                )
                .limit(1)
            )
        ).scalars().first()
        if other is not None:
            from aios.governance.security import record_cross_tenant_block_if_mismatch

            await record_cross_tenant_block_if_mismatch(
                db,
                org_id=str(org_id),
                resource=other,
                source=source,
                actor_type="human",
                actor_id=getattr(user, "id", None),
                payload={"instance": instance},
            )
            await db.commit()
    except Exception:
        logger.exception("cross-tenant probe failed for whatsapp instance=%s source=%s", instance, source)
    raise HTTPException(404, "instance not found")

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

class SendBody(BaseModel):
    instance: str
    to: str
    text: str
    provider: str = "baileys"
    approved: bool = False
    approval_action_id: str | None = None

class CallBody(BaseModel):
    instance: str
    to: str
    script: str = ""
    approved: bool = False
    approval_action_id: str | None = None

@router.post("/send")
async def whatsapp_send(
    body: SendBody,
    request: Request,
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    from sqlalchemy import select as sql_select

    from aios.core.whatsapp.service import send_via_gateway
    from aios.core.whatsapp.anti_ban.rate_limiter import allow, record_429
    from aios.core.whatsapp.metrics import msg_total
    from aios.core.action_policy import classify_tool_action
    from aios.core.audit import log_audit
    from aios.db.backend import db_session
    from aios.db.models import ChannelConnection

    # The instance must belong to the caller's org. Without this any
    # authenticated user could send from (and burn the reputation of)
    # another org's number.
    async with db_session() as db:
        await _assert_whatsapp_instance_owned(
            db,
            org_id=org_id,
            user=user,
            instance=body.instance,
            source="whatsapp.api.send_instance_not_found",
        )

        decision = classify_tool_action(
            "whatsapp_template",
            {"to": body.to, "text": body.text, "instance": body.instance, "provider": body.provider},
            context={"org_id": org_id, "source": "api.whatsapp.send"},
        )
        if decision.requires_approval or body.approved or body.approval_action_id:
            ok, reason, details = await _consume_whatsapp_approval(
                db,
                org_id=org_id,
                user=user,
                action="send",
                body=body,
                approval_action_id=body.approval_action_id,
            )
            machine_reason = details.get("reason")
            audit_details = {
                "reason": reason,
                "reason_code": machine_reason,
                "action_class": decision.action_class.value,
                "to": body.to,
                "approval_action_id": body.approval_action_id,
                **{k: v for k, v in details.items() if k != "reason"},
            }
            if not ok:
                await log_audit(
                    db, org_id, "whatsapp.send.blocked", "whatsapp",
                    user_id=getattr(user, "id", None),
                    resource_id=body.instance,
                    details=audit_details,
                )
                await db.commit()
                raise HTTPException(
                    409,
                    {
                        "error": "approval_required",
                        "reason": reason,
                        "action_class": decision.action_class.value,
                        "hint": "Create/approve a PendingAction and re-send with approval_action_id.",
                    },
                )
            await log_audit(
                db, org_id, "whatsapp.send.approval_consumed", "whatsapp",
                user_id=getattr(user, "id", None),
                resource_id=body.instance,
                details=audit_details,
            )
            await db.commit()

    if not allow(body.instance):
        msg_total.labels(instance=body.instance, direction="out", status="rate_limited").inc()
        return {"ok": False, "error": "rate_limited"}
    res = await send_via_gateway(body.instance, body.to, body.text, body.provider)
    if res.get("status_code")==429:
        record_429(body.instance)
    msg_total.labels(instance=body.instance, direction="out", status="ok" if res.get("ok") else "failed").inc()
    try:
        async with db_session() as db:
            await log_audit(
                db, org_id, "whatsapp.send.executed", "whatsapp",
                user_id=getattr(user, "id", None),
                resource_id=body.instance,
                details={
                    "ok": bool(res.get("ok")),
                    "to": body.to,
                    "approved": bool(body.approved),
                    "approval_action_id": body.approval_action_id,
                },
            )
            await db.commit()
    except Exception:
        logger.warning("whatsapp send audit failed", exc_info=True)
    return res

@router.get("/health/{instance}")
async def whatsapp_health(
    instance: str,
    provider: str = "baileys",
    user=Depends(get_current_user),
    org_id: str = Depends(get_org_id),
):
    from sqlalchemy import select

    from aios.core.whatsapp.provider.factory import get_provider
    from aios.db.backend import db_session
    from aios.db.models import ChannelConnection

    # Instance names are not unique across tenants, and the provider probes by
    # name alone. Without this check any authenticated user could read any
    # tenant's connection state by naming their instance.
    async with db_session() as db:
        mine = (
            await db.execute(
                select(ChannelConnection.id).where(
                    ChannelConnection.org_id == org_id,
                    ChannelConnection.config["instance"].as_string() == instance,
                ).limit(1)
            )
        ).first()
        if not mine:
            try:
                other = (
                    await db.execute(
                        select(ChannelConnection)
                        .where(
                            ChannelConnection.channel_type == "evolution",
                            ChannelConnection.org_id != org_id,
                            ChannelConnection.config["instance"].as_string() == instance,
                        )
                        .limit(1)
                    )
                ).scalars().first()
                if other is not None:
                    from aios.governance.security import record_cross_tenant_block_if_mismatch

                    await record_cross_tenant_block_if_mismatch(
                        db,
                        org_id=str(org_id),
                        resource=other,
                        source="whatsapp.api.health_instance_not_found",
                        actor_type="human",
                        actor_id=getattr(user, "id", None),
                        payload={"instance": instance},
                    )
                    await db.commit()
            except Exception:
                logger.exception("cross-tenant probe failed for whatsapp health instance=%s", instance)
            from fastapi import HTTPException

            raise HTTPException(404, "instance not found")
    from aios.core.whatsapp.anti_ban.health_monitor import compute
    p = get_provider(provider if provider in ("baileys","cloud","coexistence") else "baileys")
    h = await p.health(instance)
    mon = compute(instance, h.connected, fails_24h=0, qr=0, r429=0)
    return {"instance": instance, "connected": h.connected, "provider": h.provider, "risk": mon["risk"], "level": mon["level"], "coexistence": h.provider=="coexistence"}

@router.post("/migration/check")
async def migration_check(
    monthly_msgs: int,
    ban_risk: int,
    failed_pct: float = 0,
    is_coexistence: bool = False,
    user=Depends(get_current_user),
):
    from aios.core.whatsapp.migration_advisor import evaluate
    rec = evaluate(monthly_msgs, ban_risk, failed_pct, is_coexistence=is_coexistence)
    return {"should_migrate": rec.should_migrate, "reasons": rec.reasons, "urgency": rec.urgency}

@router.post("/webhook/evolution/{instance}")
async def evolution_webhook(instance: str, request: Request, x_hub_signature_256: Optional[str] = Header(None)):
    from aios.config import settings
    from aios.core.whatsapp.webhook_validator import validate
    # Fail closed: with no secret configured the validator would accept
    # anything. No Evolution instance points here (they use
    # /api/evolution/webhook/*), so rejecting breaks nothing.
    if not settings.evolution_webhook_secret:
        raise HTTPException(401, "webhook not configured")
    v = await validate(request, settings.evolution_webhook_secret, settings.redis_url)
    if not v["ok"]:
        return {"ok": False, "reason": v["reason"]}
    body = await request.json() if request.headers.get("content-type","").startswith("application/json") else {}
    # Coexistence: smb_message_echoes (App → API) → log + bypass anti-ban
    from aios.core.whatsapp.provider.evolution_coexistence import EvolutionCoexistenceProvider
    if EvolutionCoexistenceProvider.is_smb_echo(body):
        return {"ok": True, "instance": instance, "coexistence": True, "echo": True}
    # LGPD consent auto: STOP keyword
    txt = (body.get("data",{}).get("message",{}).get("conversation") or body.get("message") or "").lower()
    if txt.strip() in ("stop","parar","cancelar"):
        from aios.core.whatsapp.lgpd.consent import record_consent
        phone = body.get("data",{}).get("key",{}).get("remoteJid","")
        # Resolve the org from the instance name. Recording against "unknown"
        # used to silently drop the consent (no such org), so STOP requests
        # were never persisted and the business kept messaging people who
        # opted out. Unresolvable instances log instead of misattributing.
        try:
            from sqlalchemy import select

            from aios.db.backend import db_session
            from aios.db.models import ChannelConnection

            async with db_session() as _db:
                _conn = (
                    await _db.execute(
                        select(ChannelConnection)
                        .where(
                            ChannelConnection.channel_type == "evolution",
                            ChannelConnection.is_active == True,  # noqa: E712
                            ChannelConnection.config["instance"].as_string() == instance,
                        )
                        .order_by(ChannelConnection.id)
                        .limit(1)
                    )
                ).scalars().first()
                _org = _conn.org_id if _conn else ""
        except Exception:
            logger.exception("consent org resolution failed instance=%s", instance)
            _org = ""
        if _org:
            await record_consent(phone, "marketing", False, org_id=_org)
        else:
            logger.warning("STOP from %s not recorded: no org for instance %s", phone, instance)
    return {"ok": True, "instance": instance}

# Voice Phase B
@router.post("/call")
async def whatsapp_call(
    body: CallBody,
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    from aios.core.whatsapp.voice.call_router import start_outbound
    from aios.core.action_policy import classify_tool_action
    from aios.core.audit import log_audit
    from aios.db.backend import db_session

    async with db_session() as db:
        await _assert_whatsapp_instance_owned(
            db,
            org_id=org_id,
            user=user,
            instance=body.instance,
            source="whatsapp.api.call_instance_not_found",
        )

        decision = classify_tool_action(
            "voice_call",
            {"to": body.to, "instance": body.instance},
            context={"org_id": org_id, "source": "api.whatsapp.call"},
        )
        if decision.requires_approval or body.approved or body.approval_action_id:
            ok, reason, details = await _consume_whatsapp_approval(
                db,
                org_id=org_id,
                user=user,
                action="call",
                body=body,
                approval_action_id=body.approval_action_id,
            )
            machine_reason = details.get("reason")
            audit_details = {
                "reason": reason,
                "reason_code": machine_reason,
                "action_class": decision.action_class.value,
                "to": body.to,
                "approval_action_id": body.approval_action_id,
                **{k: v for k, v in details.items() if k != "reason"},
            }
            if not ok:
                await log_audit(
                    db, org_id, "whatsapp.call.blocked", "whatsapp",
                    user_id=getattr(user, "id", None),
                    resource_id=body.instance,
                    details=audit_details,
                )
                await db.commit()
                raise HTTPException(
                    409,
                    {
                        "error": "approval_required",
                        "reason": reason,
                        "action_class": decision.action_class.value,
                        "hint": "Create/approve a PendingAction and re-send with approval_action_id.",
                    },
                )
            await log_audit(
                db, org_id, "whatsapp.call.approval_consumed", "whatsapp",
                user_id=getattr(user, "id", None),
                resource_id=body.instance,
                details=audit_details,
            )
            await db.commit()

    result = await start_outbound(body.to, body.script)
    try:
        async with db_session() as db:
            await log_audit(
                db, org_id, "whatsapp.call.executed", "whatsapp",
                user_id=getattr(user, "id", None),
                resource_id=body.instance,
                details={
                    "ok": bool(result.get("ok")) if isinstance(result, dict) else None,
                    "to": body.to,
                    "approved": bool(body.approved),
                    "approval_action_id": body.approval_action_id,
                },
            )
            await db.commit()
    except Exception:
        logger.warning("whatsapp call audit failed", exc_info=True)
    return result

@router.get("/voice/ivr/synthesize")
async def ivr_synthesize(text: str, user=Depends(get_current_user)):
    from aios.core.voice import synthesize
    return await synthesize(text)

@router.get("/metrics/summary")
async def metrics_summary(user=Depends(get_current_user)):
    from aios.core.evolution_api import evo_fetch_instances
    instances = await evo_fetch_instances()
    return {"instances": len(instances), "gateway": "wrapper v0.1.0"}
