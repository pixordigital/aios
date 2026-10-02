"""Message delivery — background retry + dead-letter queue.

Wraps channel sends in ARQ jobs with retry and exponential backoff.
Failed messages after max retries land in a DB DLQ table.
"""

import json
import logging

from aios.core.dead_letter import write_dlq
from aios.db.backend import db_session
from aios.db.models import ChannelConnection

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY_S = 5.0


async def deliver_message(
    ctx,
    channel_connection_id: str,
    conversation_id: str,
    text: str,
    extra_data: str = "{}",
    attempt: int = 1,
    idempotency_key: str = "",
):
    """Send message via channel. Retries with backoff on failure.

    Called directly (non-streaming) or via ARQ worker.

    idempotency_key makes retries safe. If Evolution accepts a message but the
    HTTP response is lost (timeout or reset on the way back), ch.send() raises
    and the retry sends the identical text again -- the customer got the same
    reply up to three times, and Meta sees duplicate content. The key is derived
    from conversation + text + attempt-1 so every retry of the same logical
    send shares it while a genuinely new send gets a fresh one.
    """
    from aios.channels.manager import manager as channel_mgr

    if not idempotency_key:
        import hashlib as _h
        from datetime import datetime as _dt, timezone as _tz
        # NOTE: the attempt number is deliberately NOT part of the key. Including
        # it gave every retry a different key, so the pre-check could never
        # suppress the duplicate it existed to prevent. The hour bucket scopes the
        # suppression to a retry window instead of permanently.
        _bucket = _dt.now(_tz.utc).strftime("%Y%m%d%H")
        idempotency_key = _h.sha256(
            f"{conversation_id}|{text}|{_bucket}".encode("utf-8")
        ).hexdigest()[:32]

    # Skip if this exact logical send already completed. The key is a sha256 of
    # conversation + text + attempt, so it is unique per logical send and shared
    # by every retry of it.
    try:
        from aios.db.engine import async_session as _sess
        from sqlalchemy import select as _sel
        from aios.db.models import Message as _Msg
        async with _sess() as _s:
            _already = (await _s.execute(
                _sel(_Msg.id).where(_Msg.channel_message_id == idempotency_key).limit(1)
            )).first()
            if _already:
                logger.info(
                    "deliver_message: already sent under key %s, skipping retry",
                    idempotency_key,
                )
                return
    except Exception:
        logger.debug("deliver_message: idempotency pre-check unavailable")

    try:
        extra = json.loads(extra_data) if isinstance(extra_data, str) else extra_data
    except json.JSONDecodeError:
        extra = {}

    conn = None
    try:
        if text and len(text) > 4096:
            text = text[:4096]
        if channel_connection_id:
            try:
                from aios.core.whatsapp_guard import guard_send

                extra_j = json.loads(extra_data) if isinstance(extra_data, str) else extra_data
                contact = extra_j.get("from_number") or extra_j.get("to") or conversation_id
                window_open = extra_j.get("window_open", True)
                is_template = extra_j.get("is_template", False)
                # record=False: this is the pre-check, not the send. The channel
                # adapter is the layer that owns the send and records the
                # send. Recording here too made the adapter's own check read
                # back this write and refuse the message as a duplicate.
                ok, reason = await guard_send(
                    contact,
                    text,
                    is_template=is_template,
                    window_open=window_open,
                    record=False,
                )
                if not ok:
                    logger.warning("Guard block %s: %s", contact, reason)
                    if "opt-out" in reason:
                        return
                    from aios.tasks.queue import get_redis_pool as _pool

                    pool = await _pool()
                    await pool.enqueue_job(
                        "aios.core.delivery.deliver_message",
                        channel_connection_id,
                        conversation_id,
                        text,
                        extra_data,
                        attempt,
                        _defer_by=30,
                    )
                    return
            except Exception:
                # Fail CLOSED. The guard is the opt-out (LGPD) and anti-ban
                # check; swallowing its error fell through to the send below, so
                # a Redis blip delivered messages to numbers that had sent STOP,
                # into cooldowns, and outside the 24h window. Losing a message is
                # recoverable; breaking an opt-out and the WhatsApp ban limit is not.
                logger.exception(
                    "Guard raised for contact=%s; refusing to send (fail-closed)",
                    channel_connection_id,
                )
                return
        async with db_session() as db:
            conn = await db.get(ChannelConnection, channel_connection_id)
            if not conn:
                logger.warning("DLQ: channel %s not found", channel_connection_id)
                return

            # resolve agent/team if needed
            agent_or_team = None
            if conn.agent_id:
                from aios.db.models import Agent
                agent_or_team = await db.get(Agent, conn.agent_id)
            elif conn.team_id:
                from aios.db.models import Team
                from sqlalchemy.orm import selectinload
                agent_or_team = await db.get(Team, conn.team_id, options=[selectinload(Team.agents)])

            from aios.channels.base import OutboundMessage
            msg = OutboundMessage(
                conversation_id=conversation_id,
                text=text,
                channel_connection_id=channel_connection_id,
                extra_data=extra,
            )
            ch = channel_mgr.build(conn, agent_or_team, db)
            result = await ch.send(msg)

            if result is not None:
                # Record the key so a retry after a lost response is suppressed.
                #
                # By stamping the reply row the caller already saved, not by
                # inserting a second one. A new row per send meant every agent
                # reply appeared twice in the conversation and was fed to the
                # LLM twice through get_recent.
                try:
                    from sqlalchemy import select as _sel

                    from aios.db.engine import async_session as _sess
                    from aios.db.models import Message as _Msg
                    async with _sess() as _s:
                        existing = (await _s.execute(
                            _sel(_Msg).where(
                                _Msg.conversation_id == conversation_id,
                                _Msg.role == "assistant",
                                _Msg.content == text,
                            ).order_by(_Msg.created_at.desc()).limit(1)
                        )).scalars().first()
                        if existing is not None:
                            existing.channel_message_id = idempotency_key
                        else:
                            # No prior row (e.g. an operator replying from the
                            # inbox) — the send still needs its own record.
                            _s.add(_Msg(
                                conversation_id=conversation_id,
                                org_id=getattr(conn, "org_id", ""),
                                role="assistant",
                                content=text,
                                channel_message_id=idempotency_key,
                            ))
                        await _s.commit()
                except Exception:
                    logger.debug("deliver_message: could not record idempotency key")
                logger.info("Message delivered to channel %s", channel_connection_id)
                return

            # send returned None — channel unavailable
            raise ConnectionError("Channel send returned None")

    except Exception as exc:
        logger.warning("Delivery attempt %d/%d failed for channel %s: %s",
                       attempt, _MAX_RETRIES, channel_connection_id, exc)
        if attempt < _MAX_RETRIES:
            # re-enqueue with backoff via ARQ
            from aios.tasks.queue import get_redis_pool
            pool = await get_redis_pool()
            delay = _BASE_DELAY_S * (2 ** (attempt - 1))
            await pool.enqueue_job(
                "aios.core.delivery.deliver_message",
                channel_connection_id,
                conversation_id,
                text,
                extra_data,
                attempt + 1,
                idempotency_key,  # same logical send -> same key -> suppressed
                _defer_by=delay,
            )
        else:
            # max retries exceeded — DLQ
            await write_dlq(
                direction="outbound",
                channel_type=getattr(conn, "channel_type", ""),
                job_name="aios.core.delivery.deliver_message",
                payload={"args": [channel_connection_id, conversation_id, text, extra_data], "kwargs": {}},
                error=str(exc),
                org_id=getattr(conn, "org_id", None),
                channel_connection_id=channel_connection_id,
                conversation_id=conversation_id,
            )
            logger.error("DLQ: message to channel %s failed after %d attempts",
                         channel_connection_id, _MAX_RETRIES)