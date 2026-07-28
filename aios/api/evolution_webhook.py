"""Evolution API webhook — inbound WhatsApp messages from Evolution API."""

import hashlib
import hmac
import logging

from fastapi import APIRouter, HTTPException, Request

from aios.channels.base import OutboundMessage
from aios.channels.manager import manager as channel_mgr
from aios.core.limits import check_org_limits, track_usage
from aios.db.backend import db_session
from aios.db.models import Agent, ChannelConnection, Conversation, Message, Team
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/evolution", tags=["evolution"])


@router.get("/webhook/{instance}")
async def verify_evolution_webhook(instance: str):
    """Evolution API GET verification."""
    return {"status": "ok", "instance": instance}


@router.post("/webhook/{instance}")
async def evolution_webhook(instance: str, request: Request):
    """Receive incoming WhatsApp messages from Evolution API."""
    body = await request.json()
    logger.debug("Evolution webhook: %s event=%s", instance, body.get("event", "?"))

    # verify webhook signature if configured
    sig = request.headers.get("x-evolution-signature", "")
    if sig:
        instance_key = _get_evolution_api_key(instance)
        if instance_key and not _verify_evolution_sig(sig, body, instance_key):
            logger.warning("Evolution webhook signature mismatch for instance %s", instance)
            return {"status": "ignored"}

    try:
        event = body.get("event", "")
        data = body.get("data", {})

        # Only handle new messages
        if event not in ("messages.upsert", "messages.update"):
            return {"status": "ok"}

        # Extract message details
        key = data.get("key", {})
        msg_text = ""
        msg_from = ""

        # Evolution API payload structure
        remote_jid = key.get("remoteJid", "")
        if remote_jid:
            # Remove @s.whatsapp.net suffix
            msg_from = remote_jid.split("@")[0]

        message_data = data.get("message", {})
        if "conversation" in message_data:
            msg_text = message_data["conversation"]
        elif "extendedTextMessage" in message_data:
            msg_text = message_data["extendedTextMessage"].get("text", "")

        if not msg_text or not msg_from:
            return {"status": "ok"}

        # Don't process outgoing messages (from our own instance)
        if data.get("key", {}).get("fromMe"):
            return {"status": "ok"}

        async with db_session() as db:
            # Find matching Evolution API channel by instance name
            result = await db.execute(
                select(ChannelConnection).where(
                    ChannelConnection.channel_type == "evolution",
                    ChannelConnection.is_active == True,
                )
            )
            conn = None
            for ch in result.scalars():
                if ch.config.get("instance") == instance:
                    conn = ch
                    break

            if not conn:
                logger.warning("No active Evolution channel for instance %s", instance)
                return {"status": "ok"}

            # resolve agent or team
            agent_or_team = None
            if conn.agent_id:
                agent_or_team = await db.get(Agent, conn.agent_id)
            elif conn.team_id:
                agent_or_team = await db.get(
                    Team, conn.team_id, options=[selectinload(Team.agents)]
                )

            # find or create conversation
            ext_id = f"evo_{msg_from}"
            conv = (await db.execute(
                select(Conversation).where(
                    Conversation.channel == "evolution",
                    Conversation.external_id == ext_id,
                )
            )).scalars().first()

            if not conv:
                conv = Conversation(
                    org_id=conn.org_id,
                    channel="evolution",
                    external_id=ext_id,
                    channel_connection_id=conn.id,
                    agent_id=conn.agent_id,
                    team_id=conn.team_id,
                    extra_data={"from_number": msg_from, "instance": instance},
                )
                db.add(conv)
                await db.commit()
                await db.refresh(conv)

            # save inbound message
            db.add(Message(
                conversation_id=conv.id,
                role="user",
                content=msg_text,
                extra_data={"from_number": msg_from, "instance": instance},
            ))
            await db.commit()

            # check org limits
            allowed, reason = await check_org_limits(conn.org_id, db)
            if not allowed:
                logger.warning("Evolution limit hit for org %s: %s", conn.org_id, reason)
                return {"status": "ok"}

            # route to agent
            reply_text = None
            if agent_or_team:
                try:
                    if hasattr(agent_or_team, "agents"):  # Team
                        from aios.core.orchestrator import TeamOrchestrator
                        orch = TeamOrchestrator(agent_or_team, list(agent_or_team.agents))
                        reply_text = await orch.handle_message(conv.id, msg_text)
                    else:  # Agent
                        from aios.core.agent import AgentRuntime
                        runtime = AgentRuntime(agent_or_team)
                        reply_text = await runtime.run(conv.id, msg_text)

                    if reply_text:
                        db.add(Message(
                            conversation_id=conv.id,
                            role="assistant",
                            content=reply_text,
                            agent_id=getattr(agent_or_team, "id", None),
                        ))
                        await db.commit()

                        # send reply via Evolution API
                        ch = channel_mgr.build(conn, agent_or_team, db)
                        await ch.send(OutboundMessage(
                            conversation_id=conv.id,
                            text=reply_text,
                            channel_connection_id=conn.id,
                            extra_data={"from_number": msg_from},
                        ))
                except Exception:
                    logger.exception("Evolution routing failed for %s", msg_from)

    except Exception:
        logger.exception("Evolution webhook processing failed")

    return {"status": "ok"}


def _get_evolution_api_key(instance_name: str) -> str:
    """Look up API key for Evolution instance from channel configs."""
    from aios.db.engine import async_session
    from sqlalchemy import select as sql_select
    import asyncio
    try:
        loop = asyncio.new_event_loop()
        conn = loop.run_until_complete(async_session())
        try:
            result = loop.run_until_complete(
                conn.execute(
                    sql_select(ChannelConnection.config).where(
                        ChannelConnection.channel_type == "evolution",
                        ChannelConnection.is_active == True,
                    )
                )
            )
            for row in result.scalars():
                if row.get("instance") == instance_name:
                    return row.get("api_key", "")
            return ""
        finally:
            loop.run_until_complete(conn.close())
            loop.close()
    except Exception:
        logger.debug("Could not fetch Evolution API key for signature check")
        return ""


def _verify_evolution_sig(signature: str, body: dict, api_key: str) -> bool:
    """Verify Evolution webhook HMAC-SHA256 signature."""
    import json
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True)
    expected = hmac.new(api_key.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)
