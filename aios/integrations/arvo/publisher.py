"""Outbox publisher — pending → HTTP to ARVO with retry."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, update

from aios.config import settings
from aios.db.engine import async_session
from aios.db.models import IntegrationOutbox

logger = logging.getLogger(__name__)


async def enqueue_outbox(
    event_type: str,
    payload: dict,
    business_trace_id: str | None = None,
    peer: str = "arvo",
    idempotency_key: str | None = None,
) -> str:
    """Insert durable pending row and best-effort schedule immediate flush."""
    key = idempotency_key or str(uuid.uuid4())
    async with async_session() as session:
        existing = await session.scalar(
            select(IntegrationOutbox).where(IntegrationOutbox.idempotency_key == key)
        )
        if existing:
            return existing.id
        row = IntegrationOutbox(
            peer=peer,
            event_type=event_type,
            payload=payload,
            business_trace_id=business_trace_id,
            idempotency_key=key,
            status="pending",
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        outbox_id = row.id
    try:
        from aios.tasks.queue import enqueue_job

        await enqueue_job("integration_outbox_flush_job", outbox_id=outbox_id)
    except Exception:
        logger.debug(
            "outbox %s immediate flush unavailable; cron will retry",
            outbox_id[:8],
            exc_info=True,
        )
    return outbox_id


async def _claim_rows(
    batch: int, outbox_id: str | None = None
) -> list[IntegrationOutbox]:
    stale_before = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
    async with async_session() as session:
        await session.execute(
            update(IntegrationOutbox)
            .where(
                IntegrationOutbox.status == "processing",
                IntegrationOutbox.updated_at < stale_before,
            )
            .values(status="pending")
        )
        if outbox_id:
            candidate_ids = [outbox_id]
        else:
            ids = await session.scalars(
                select(IntegrationOutbox.id)
                .where(IntegrationOutbox.status == "pending")
                .order_by(IntegrationOutbox.created_at)
                .limit(batch)
            )
            candidate_ids = list(ids)
        claimed_ids = []
        for candidate_id in candidate_ids:
            result = await session.execute(
                update(IntegrationOutbox)
                .where(
                    IntegrationOutbox.id == candidate_id,
                    IntegrationOutbox.status == "pending",
                )
                .values(status="processing", attempts=IntegrationOutbox.attempts + 1)
            )
            if result.rowcount:
                claimed_ids.append(candidate_id)
        await session.commit()
        if not claimed_ids:
            return []
        return list(
            await session.scalars(
                select(IntegrationOutbox).where(IntegrationOutbox.id.in_(claimed_ids))
            )
        )


async def _deliver(row: IntegrationOutbox, raise_errors: bool) -> bool:
    from aios.integrations.arvo.client import send_event

    try:
        await send_event(
            row.event_type,
            row.payload,
            idempotency_key=row.idempotency_key,
        )
    except Exception as error:
        retryable = (
            not isinstance(error, httpx.HTTPStatusError)
            or error.response.status_code in (408, 429)
            or error.response.status_code >= 500
        )
        status = "pending" if retryable and row.attempts < 5 else "failed"
        async with async_session() as session:
            current = await session.get(IntegrationOutbox, row.id)
            if current and current.status == "processing":
                current.status = status
                current.last_error = str(error)[:500]
                await session.commit()
        if raise_errors:
            raise
        logger.warning(
            "outbox %s attempt %d failed: %s", row.id[:8], row.attempts, error
        )
        return False
    async with async_session() as session:
        current = await session.get(IntegrationOutbox, row.id)
        if current and current.status == "processing":
            current.status = "sent"
            current.sent_at = datetime.now(UTC).replace(tzinfo=None)
            current.last_error = None
            await session.commit()
    return True


async def flush_outbox(batch: int = 20) -> dict:
    """Send claimed rows to peer. Returns send counters."""
    if not settings.arvo_integration_enabled or not settings.arvo_base_url:
        return {"skipped": True, "reason": "integration disabled"}
    rows = await _claim_rows(batch)
    sent = 0
    failed = 0
    for row in rows:
        if await _deliver(row, raise_errors=False):
            sent += 1
        else:
            failed += 1
    return {"sent": sent, "failed": failed}


async def integration_outbox_flush(
    ctx,
    outbox_id: str | None = None,
    batch: int = 20,
):
    """ARQ job: flush one id or batch of pending rows."""
    if not settings.arvo_integration_enabled or not settings.arvo_base_url:
        return {"skipped": True}
    if outbox_id:
        rows = await _claim_rows(1, outbox_id=outbox_id)
        if not rows:
            return {"skipped": True}
        await _deliver(rows[0], raise_errors=True)
        return {"sent": 1}
    return await flush_outbox(batch=batch)
