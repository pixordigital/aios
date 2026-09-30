"""Write real ban signals to whatsapp_events.

This is the piece that was missing: nothing in the send path ever told the rest
of the system that WhatsApp had answered 403, 429, or dropped the connection.
Without it every risk number would have been invented.
"""

import logging

logger = logging.getLogger(__name__)

# Bodies that mean "your number is in trouble", not "your message was bad".
BAN_WORDS = ("ban", "blocked", "forbidden", "unauthorized", "not authorized", "suspend", "disabled")


async def record_event(org_id: str, instance: str, kind: str, detail: str = ""):
    """Append one signal. Never raises — telemetry must not break a send."""
    if not org_id:
        return
    try:
        from aios.db.backend import db_session
        from aios.db.models import WhatsappEvent

        async with db_session() as db:
            db.add(
                WhatsappEvent(
                    org_id=org_id,
                    instance=(instance or "")[:80],
                    kind=kind[:30],
                    detail=(detail or "")[:200],
                )
            )
            await db.commit()
    except Exception:
        logger.debug("ban-risk: could not record %s for %s", kind, instance)


def looks_like_ban(status_code: int, body: str) -> bool:
    """Did Evolution's error text actually indicate a ban/block?

    Kept separate from status_code alone because 403 is also returned for a
    malformed payload, and treating that as a ban would cry wolf.
    """
    if status_code not in (401, 403, 440, 441):
        return False
    low = (body or "").lower()
    return any(w in low for w in BAN_WORDS)


async def record_response(org_id: str, instance: str, status_code: int, body: str = ""):
    """Turn an Evolution response into the right signal."""
    if status_code == 429:
        await record_event(org_id, instance, "http_429", f"HTTP 429")
        return "http_429"
    if looks_like_ban(status_code, body):
        await record_event(org_id, instance, "ban_signal", f"HTTP {status_code}")
        return "ban_signal"
    if status_code in (401, 403):
        await record_event(org_id, instance, "http_403", f"HTTP {status_code}")
        return "http_403"
    return None


async def gather_counts(org_id: str, instance: str | None = "", days: int = 1) -> dict:
    """Count events per kind for an instance over the lookback window.

    instance=None skips the instance filter (org-wide totals for the header).
    """
    if not org_id:
        return {}
    try:
        import datetime

        from sqlalchemy import func as sql_func
        from sqlalchemy import select as sql_select

        from aios.db.backend import db_session
        from aios.db.models import WhatsappEvent

        since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
        q = (
            sql_select(WhatsappEvent.kind, sql_func.count())
            .where(
                WhatsappEvent.org_id == org_id,
                WhatsappEvent.created_at >= since,
            )
        )
        if instance is not None:
            q = q.where(WhatsappEvent.instance == (instance or ""))
        async with db_session() as db:
            rows = (await db.execute(q.group_by(WhatsappEvent.kind))).all()
        return {k: int(n) for k, n in rows}
    except Exception:
        logger.debug("ban-risk: could not gather counts")
        return {}


async def sent_today(org_id: str, instance: str) -> int:
    return (await gather_counts(org_id, instance, days=1)).get("sent", 0)


async def is_quarantined(org_id: str, instance: str) -> bool:
    """True when corroborated ban evidence says STOP sending on this instance.

    Counts only — the send path calls this, so it stays a single grouped
    query. Velocity is already capped by guard_send's warmup limits; assuming
    connected here because a disconnected instance fails at Evolution anyway.
    """
    from aios.core.whatsapp.anti_ban.risk import score_from_events

    counts = await gather_counts(org_id, instance, days=1)
    return score_from_events(counts, connected=True).quarantined
