"""Slack webhook — inbound events from Slack app."""

import hashlib
import hmac
import logging
import time

from fastapi import APIRouter, HTTPException, Request

from aios.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/slack", tags=["slack"])


def _verify_slack_signature(request: Request, body: bytes) -> bool:
    """Verify Slack request signature."""
    if not settings.slack_signing_secret:
        return True  # No secret configured, skip verification

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
        settings.slack_signing_secret.encode(), basestring.encode(), hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, sig)


@router.post("/webhook")
async def slack_webhook(request: Request):
    """Receive Slack events → dispatch to agent."""
    raw_body = await request.body()

    if not _verify_slack_signature(request, raw_body):
        logger.warning("Slack webhook signature verification failed")
        raise HTTPException(401, "Invalid signature")

    try:
        body = await request.json()
    except Exception:
        body = {}

    # URL verification challenge
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    # Event callback
    if body.get("type") == "event_callback":
        event = body.get("event", {})
        event_type = event.get("type", "")

        if event_type == "message" and not event.get("bot_id"):
            # User message (not from bot)
            text = event.get("text", "")
            user_id = event.get("user", "")
            channel_id = event.get("channel", "")
            team_id = event.get("team_id", "")
            ts = event.get("ts", "")

            from aios.core.dispatch import dispatch_inbound

            async with (await __import__("aios.db.backend", fromlist=["db_session"])).db_session() as db:
                from aios.db.models import ChannelConnection
                from sqlalchemy import select

                result = await db.execute(
                    select(ChannelConnection).where(
                        ChannelConnection.channel_type == "slack",
                        ChannelConnection.is_active == True,
                    )
                )
                conn = result.scalars().first()

                if conn:
                    await dispatch_inbound(
                        channel_type="slack",
                        channel_connection_id=conn.id,
                        conversation_id="",
                        text=text,
                        user_id=user_id,
                        extra_data={
                            "event": "message",
                            "channel_id": channel_id,
                            "team_id": team_id,
                            "ts": ts,
                            "thread_ts": event.get("thread_ts", ""),
                        },
                    )

        elif event_type == "app_mention":
            # Bot mentioned
            text = event.get("text", "")
            user_id = event.get("user", "")
            channel_id = event.get("channel", "")
            team_id = event.get("team_id", "")

            from aios.core.dispatch import dispatch_inbound

            async with (await __import__("aios.db.backend", fromlist=["db_session"])).db_session() as db:
                from aios.db.models import ChannelConnection
                from sqlalchemy import select

                result = await db.execute(
                    select(ChannelConnection).where(
                        ChannelConnection.channel_type == "slack",
                        ChannelConnection.is_active == True,
                    )
                )
                conn = result.scalars().first()

                if conn:
                    await dispatch_inbound(
                        channel_type="slack",
                        channel_connection_id=conn.id,
                        conversation_id="",
                        text=text,
                        user_id=user_id,
                        extra_data={
                            "event": "app_mention",
                            "channel_id": channel_id,
                            "team_id": team_id,
                        },
                    )

        elif event_type == "reaction_added":
            # Reaction added to message
            reaction = event.get("reaction", "")
            user_id = event.get("user", "")
            item = event.get("item", {})
            channel_id = item.get("channel", "")
            ts = item.get("ts", "")

            from aios.core.dispatch import dispatch_inbound

            async with (await __import__("aios.db.backend", fromlist=["db_session"])).db_session() as db:
                from aios.db.models import ChannelConnection
                from sqlalchemy import select

                result = await db.execute(
                    select(ChannelConnection).where(
                        ChannelConnection.channel_type == "slack",
                        ChannelConnection.is_active == True,
                    )
                )
                conn = result.scalars().first()

                if conn:
                    await dispatch_inbound(
                        channel_type="slack",
                        channel_connection_id=conn.id,
                        conversation_id="",
                        text=f"reaction:{reaction}",
                        user_id=user_id,
                        extra_data={
                            "event": "reaction_added",
                            "reaction": reaction,
                            "channel_id": channel_id,
                            "message_ts": ts,
                        },
                    )

    return {"status": "ok"}


@router.get("/webhook")
async def slack_webhook_verify():
    """Health check endpoint."""
    return {"status": "ok", "service": "slack-webhook"}