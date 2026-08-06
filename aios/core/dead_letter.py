"""Dead-letter queue — persistent failed jobs, DB-backed.

Both inbound (webhook dispatch, process_inbound) and outbound
(deliver_message) directions land here after exhausting retries.
Admin re-enqueues entries via ARQ for manual recovery.
"""

import logging

from sqlalchemy import select

from aios.db.backend import db_session
from aios.db.models import DeadLetter, _now

logger = logging.getLogger(__name__)


def _entry_to_dict(entry: DeadLetter) -> dict:
    return {
        "id": entry.id,
        "org_id": entry.org_id,
        "channel_type": entry.channel_type,
        "channel_connection_id": entry.channel_connection_id,
        "conversation_id": entry.conversation_id,
        "direction": entry.direction,
        "job_name": entry.job_name,
        "payload": entry.payload,
        "error": entry.error,
        "attempts": entry.attempts,
        "status": entry.status,
        "retried_at": entry.retried_at.isoformat() if entry.retried_at else None,
        "created_at": entry.created_at.isoformat(),
    }


async def write_dlq(
    direction: str,
    channel_type: str,
    job_name: str,
    payload: dict,
    error: str,
    org_id: str | None = None,
    channel_connection_id: str | None = None,
    conversation_id: str | None = None,
) -> str | None:
    """Persist a failed message to the dead-letter queue. Returns entry id."""
    async with db_session() as db:
        entry = DeadLetter(
            org_id=org_id,
            channel_type=channel_type,
            channel_connection_id=channel_connection_id,
            conversation_id=conversation_id,
            direction=direction,
            job_name=job_name,
            payload=payload,
            error=error[:2000],
        )
        db.add(entry)
        try:
            await db.commit()
        except Exception:
            logger.exception("DLQ insert failed")
            return None
        return entry.id


async def list_dlq(limit: int = 50) -> list[dict]:
    async with db_session() as db:
        rows = (await db.execute(
            select(DeadLetter).order_by(DeadLetter.created_at.desc()).limit(limit)
        )).scalars().all()
        return [_entry_to_dict(e) for e in rows]


async def retry_dlq(entry_id: str) -> dict:
    """Re-enqueue a DLQ'd job via ARQ. Payload carries the original job args."""
    async with db_session() as db:
        entry = await db.get(DeadLetter, entry_id)
        if not entry:
            return {"ok": False, "error": "not found"}
        entry.retried_at = _now()
        entry.status = "retried"
        await db.commit()

    from aios.tasks.queue import get_redis_pool
    pool = await get_redis_pool()
    await pool.enqueue_job(entry.job_name, **entry.payload)
    return {"ok": True}


async def clear_dlq() -> int:
    async with db_session() as db:
        rows = (await db.execute(select(DeadLetter))).scalars().all()
        for r in rows:
            await db.delete(r)
        await db.commit()
        return len(rows)
