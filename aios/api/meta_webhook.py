"""Meta template status webhook.

Meta notifies template status changes with the `message_template_status_update`
event on the WABA's subscribed webhook. Two rules matter here:

1. **Verify before acting.** The payload names a template id, so acting on an
   unverified request would let anyone flip a tenant's template state. The
   shared secret is per-connection, so one tenant cannot mutate another.
2. **Never invent a rejection reason.** Meta's rejected_reason is a closed enum
   and NONE is a valid value; duplication — a common cause — is absent from it.
   We copy what Meta sent and say plainly when it says nothing.

A webhook alone is not sufficient: review takes up to 24h and Meta drops events,
so `aios/tasks/jobs.py:template_status_reconcile_job` re-pulls anything that has
been PENDING for a while.
"""

import hashlib
import hmac
import logging

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from aios.db.backend import db_session
from aios.db.models import WhatsappConnection, WhatsappTemplate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/whatsapp/webhook", tags=["whatsapp-meta"])

REJECTED_WITH_NO_REASON = (
    "Meta rejeitou sem informar um motivo específico (rejected_reason = NONE). "
    "Causas comuns que não aparecem nesse campo: corpo idêntico a um template já "
    "aprovado, ou categoria incorreta."
)


def _expected_secret(conn) -> str:
    from aios.core.secrets import decrypt_secret

    try:
        return decrypt_secret(getattr(conn, "webhook_secret_enc", "") or "")
    except Exception:
        return ""


def apply_meta_state(tpl, *, status: str = "", reason: str | None = None) -> None:
    """Copy Meta's verdict onto our row without embellishing it."""
    if status:
        tpl.status = status.upper()
    tpl.rejected_reason = reason or None
    if reason and reason != "NONE":
        tpl.rejection_note = f"Meta informou: {reason}"
    elif (tpl.status or "") == "REJECTED":
        tpl.rejection_note = REJECTED_WITH_NO_REASON
    else:
        tpl.rejection_note = ""


@router.post("/templates")
async def meta_template_status_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "invalid json")

    entries = (payload or {}).get("entry") or []
    waba_id = ""
    for e in entries:
        waba_id = (e.get("id") or "").strip()
        if waba_id:
            break
    if not waba_id:
        return {"status": "ignored", "reason": "no waba id"}

    async with db_session() as db:
        conn = (await db.execute(
            select(WhatsappConnection).where(WhatsappConnection.waba_id == waba_id)
        )).scalars().first()
        if not conn:
            # Answer 200 so Meta stops retrying an account we do not know, but
            # do not touch anything.
            logger.warning("template webhook for unknown waba %s", waba_id)
            return {"status": "ignored", "reason": "unknown waba"}

        expected = _expected_secret(conn)
        got = request.headers.get("x-aios-webhook-secret") or ""
        internal_ok = bool(expected) and hmac.compare_digest(got, expected)

        # Meta itself signs with the App Secret as X-Hub-Signature-256. The
        # custom header above only works for callers we control, and Meta is
        # not one of them — without this branch every real Meta callback 401s
        # and template statuses update only via the reconcile cron.
        meta_ok = False
        hub_sig = request.headers.get("x-hub-signature-256") or ""
        try:
            from aios.config import settings as _settings

            app_secret = (_settings.whatsapp_app_secret or "").strip()
        except Exception:
            app_secret = ""
        if app_secret and hub_sig.startswith("sha256="):
            raw = await request.body()
            digest = hmac.new(app_secret.encode(), raw, hashlib.sha256).hexdigest()
            meta_ok = hmac.compare_digest(hub_sig, "sha256=" + digest)

        # Fail closed: no configured secret means nobody may set our state.
        if not (internal_ok or meta_ok):
            logger.error("template webhook auth failed for waba %s", waba_id)
            raise HTTPException(401, "invalid webhook secret")

        touched = 0
        for entry in entries:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                if value.get("event") not in (
                    "message_template_status_update",
                    "message_template_quality_update",
                ):
                    continue
                meta_id = value.get("message_template_id") or value.get("template_id")
                if not meta_id:
                    continue
                # org_id in the predicate: a meta_template_id must never update a
                # row belonging to a different tenant.
                tpl = (await db.execute(
                    select(WhatsappTemplate).where(
                        WhatsappTemplate.meta_template_id == str(meta_id),
                        WhatsappTemplate.org_id == conn.org_id,
                    )
                )).scalars().first()
                if not tpl:
                    logger.info("webhook for unknown template %s (org %s)", meta_id, conn.org_id)
                    continue
                apply_meta_state(
                    tpl,
                    status=value.get("status") or "",
                    reason=value.get("rejected_reason"),
                )
                touched += 1
        await db.commit()
    return {"status": "ok", "updated": touched}