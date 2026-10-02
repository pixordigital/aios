"""Slack webhook — inbound events from Slack app.

Routing: each Slack channel (a manager's or orchestrator's channel) maps to its
own ChannelConnection via config.slack_channel_id. With no match, falls back to
the first active Slack connection — which is the correct behaviour for DM-only
setups, since each person gets their own DM channel.
"""

import hashlib
import hmac
import logging
import time

from fastapi import APIRouter, HTTPException, Request

from aios.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/slack", tags=["slack"])


def _verify_slack_signature(request: Request, body: bytes, secret: str = "") -> bool:
    """Verify Slack request signature.

    Falls back to the global setting when the connection has no secret of its own.
    """
    secret = secret or settings.slack_signing_secret
    if not secret:
        # Fail CLOSED. Returning True here meant any internet user could POST a
        # forged event_callback and inject messages into a tenant's agent. An
        # unconfigured webhook must reject, not authenticate everyone.
        raise HTTPException(
            503, "Slack signing secret not configured; refusing unauthenticated webhook"
        )

    timestamp = request.headers.get("x-slack-request-timestamp", "")
    sig = request.headers.get("x-slack-signature", "")

    if not timestamp or not sig:
        return False

    # Prevent replay attacks (5 min window)
    if abs(time.time() - int(timestamp)) > 300:
        logger.warning("Slack webhook timestamp too old")
        return False

    basestring = f"v0:{timestamp}:{body.decode()}"
    expected = "v0=" + hmac.new(
        secret.encode(), basestring.encode(), hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, sig)


async def _find_connection(db, slack_channel_id: str = ""):
    """Route by Slack channel.

    Each team/manager 1:1 channel gets its own ChannelConnection with
    config.slack_channel_id set. Falls back to the first active Slack conn.
    """
    from sqlalchemy import select

    from aios.db.models import ChannelConnection

    result = await db.execute(
        select(ChannelConnection).where(
            ChannelConnection.channel_type == "slack",
            ChannelConnection.is_active == True,
        )
    )
    conns = result.scalars().all()
    if slack_channel_id:
        for c in conns:
            cfg = c.config or {}
            if isinstance(cfg, dict) and cfg.get("slack_channel_id") == slack_channel_id:
                return c
    return conns[0] if conns else None


def _channel_id_of(event: dict) -> str:
    """Slack puts the channel in different places depending on the event type."""
    return event.get("channel") or (event.get("item", {}) or {}).get("channel", "")


@router.post("/webhook")
async def slack_webhook(request: Request):
    """Receive Slack events → dispatch to agent."""
    raw_body = await request.body()

    try:
        body = await request.json()
    except Exception:
        body = {}

    # URL verification challenge
    if body.get("type") == "url_verification":
        if not _verify_slack_signature(request, raw_body):
            logger.warning("Slack webhook signature verification failed")
            raise HTTPException(401, "Invalid signature")
        return {"challenge": body.get("challenge", "")}

    # Resolve the connection first: each one may carry its own signing secret.
    from aios.db.backend import db_session

    event = body.get("event", {}) if body.get("type") == "event_callback" else {}
    event_type = event.get("type", "")
    channel_id = _channel_id_of(event)

    async with db_session() as db:
        conn = await _find_connection(db, channel_id)
        conn_secret = (conn.config or {}).get("signing_secret", "") if conn else ""

    if not _verify_slack_signature(request, raw_body, conn_secret):
        logger.warning("Slack webhook signature verification failed")
        raise HTTPException(401, "Invalid signature")

    if not conn:
        logger.warning("Slack webhook: no active slack connection for channel %s", channel_id)
        return {"status": "ok"}

    if body.get("type") != "event_callback":
        return {"status": "ok"}

    from aios.core.dispatch import dispatch_inbound

    if event_type == "message" and not event.get("bot_id"):
        # User message — covers both message.channels and message.im (DMs)
        await dispatch_inbound(
            channel_type="slack",
            channel_connection_id=conn.id,
            conversation_id="",
            text=event.get("text", ""),
            user_id=event.get("user", ""),
            extra_data={
                "event": "message",
                "channel_id": channel_id,
                "team_id": event.get("team_id", ""),
                "ts": event.get("ts", ""),
                "thread_ts": event.get("thread_ts", ""),
            },
        )

    elif event_type == "app_mention":
        # Bot mentioned
        await dispatch_inbound(
            channel_type="slack",
            channel_connection_id=conn.id,
            conversation_id="",
            text=event.get("text", ""),
            user_id=event.get("user", ""),
            extra_data={
                "event": "app_mention",
                "channel_id": channel_id,
                "team_id": event.get("team_id", ""),
            },
        )

    elif event_type == "reaction_added":
        # Reaction added to message
        item = event.get("item", {})
        await dispatch_inbound(
            channel_type="slack",
            channel_connection_id=conn.id,
            conversation_id="",
            text=f"reaction:{event.get('reaction', '')}",
            user_id=event.get("user", ""),
            extra_data={
                "event": "reaction_added",
                "reaction": event.get("reaction", ""),
                "channel_id": channel_id,
                "message_ts": item.get("ts", ""),
            },
        )

    return {"status": "ok"}


@router.get("/webhook")
async def slack_webhook_verify():
    """Health check endpoint."""
    return {"status": "ok", "service": "slack-webhook"}
