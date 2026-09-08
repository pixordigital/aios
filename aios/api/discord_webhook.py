"""Discord webhook — inbound messages from Discord bot."""

import hashlib
import hmac
import logging

from fastapi import APIRouter, HTTPException, Request

from aios.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/discord", tags=["discord"])


@router.post("/webhook")
async def discord_webhook(request: Request):
    """Receive Discord messages via webhook → dispatch to agent."""
    raw_body = await request.body()

    # Verify signature (Discord uses Ed25519, but we check public key)
    # For simplicity, use shared secret if configured
    if settings.discord_webhook_secret:
        sig = request.headers.get("x-signature-ed25519", "")
        timestamp = request.headers.get("x-signature-timestamp", "")
        if not sig or not timestamp:
            logger.warning("Discord webhook missing signature headers")
            raise HTTPException(401, "Missing signature headers")
        # Discord Ed25519 verification would go here
        # For now, accept if secret matches a simple HMAC
        expected = hmac.new(
            settings.discord_webhook_secret.encode(),
            timestamp.encode() + raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            logger.warning("Discord webhook signature mismatch")
            raise HTTPException(401, "Invalid signature")

    try:
        body = await request.json()
    except Exception:
        body = {}

    # Discord interaction types
    interaction_type = body.get("type", 0)

    if interaction_type == 1:
        # PING - Discord health check
        return {"type": 1}  # PONG

    if interaction_type == 2:
        # APPLICATION_COMMAND - slash command
        data = body.get("data", {})
        command_name = data.get("name", "")
        user_id = body.get("member", {}).get("user", {}).get("id", "")
        guild_id = body.get("guild_id", "")
        channel_id = body.get("channel_id", "")

        from aios.core.dispatch import dispatch_inbound

        async with (await __import__("aios.db.backend", fromlist=["db_session"])).db_session() as db:
            from aios.db.models import ChannelConnection
            from sqlalchemy import select

            result = await db.execute(
                select(ChannelConnection).where(
                    ChannelConnection.channel_type == "discord",
                    ChannelConnection.is_active == True,
                )
            )
            conn = result.scalars().first()

            if conn:
                await dispatch_inbound(
                    channel_type="discord",
                    channel_connection_id=conn.id,
                    conversation_id="",
                    text=f"/{command_name}",
                    user_id=user_id,
                    extra_data={
                        "event": "command",
                        "command": command_name,
                        "guild_id": guild_id,
                        "channel_id": channel_id,
                        "interaction_id": body.get("id", ""),
                        "interaction_token": body.get("token", ""),
                    },
                )

        return {"type": 5}  # ACK with deferred response

    if interaction_type == 4:
        # MESSAGE_COMPONENT - button/select menu
        data = body.get("data", {})
        custom_id = data.get("custom_id", "")
        user_id = body.get("member", {}).get("user", {}).get("id", "")

        from aios.core.dispatch import dispatch_inbound

        async with (await __import__("aios.db.backend", fromlist=["db_session"])).db_session() as db:
            from aios.db.models import ChannelConnection
            from sqlalchemy import select

            result = await db.execute(
                select(ChannelConnection).where(
                    ChannelConnection.channel_type == "discord",
                    ChannelConnection.is_active == True,
                )
            )
            conn = result.scalars().first()

            if conn:
                await dispatch_inbound(
                    channel_type="discord",
                    channel_connection_id=conn.id,
                    conversation_id="",
                    text=f"component:{custom_id}",
                    user_id=user_id,
                    extra_data={
                        "event": "component",
                        "custom_id": custom_id,
                        "interaction_id": body.get("id", ""),
                        "interaction_token": body.get("token", ""),
                    },
                )

        return {"type": 5}

    return {"type": 1}


@router.get("/webhook")
async def discord_webhook_verify():
    """Health check endpoint."""
    return {"status": "ok", "service": "discord-webhook"}