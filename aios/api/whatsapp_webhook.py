"""WhatsApp Cloud API webhook - inbound messages."""

import hashlib
import hmac
import logging

from fastapi import APIRouter, HTTPException, Request

from aios.channels.base import OutboundMessage
from aios.channels.manager import manager as channel_mgr
from aios.core.limits import check_org_limits
from aios.db.backend import db_session
from aios.db.models import Agent, ChannelConnection, Conversation, Message, Team
from aios.config import settings
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

# ponytail: verify webhook signature in production
WHATSAPP_VERIFY_TOKEN = "aios_verify_2024"


@router.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN and challenge:
        return int(challenge)
    raise HTTPException(403, "Verification failed")


@router.post("/webhook")
async def inbound_webhook(request: Request):
    body = await request.json()
    logger.debug("WhatsApp webhook: %s", body)

    # verify WhatsApp signature if app secret is configured
    sig = request.headers.get("x-hub-signature-256", "")
    if sig and settings.whatsapp_app_secret:
        raw_body = await request.body()
        expected = "sha256=" + hmac.new(
            settings.whatsapp_app_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            logger.warning("WhatsApp webhook signature mismatch")
            return {"status": "ignored"}

    # extract message info for retry tracking
    entry = (body.get("entry") or [{}])[0]
    change = (entry.get("changes") or [{}])[0]
    value = change.get("value", {})
    messages = value.get("messages") or []
    msg_id = messages[0].get("id", "") if messages else ""

    from aios.core.retry import process_with_retry
    await process_with_retry(_process_webhook, body, channel_type="whatsapp", message_id=msg_id)
    return {"status": "ok"}


async def _process_webhook(body: dict):
    """Process WhatsApp webhook. Raises on failure for retry."""
    entry = (body.get("entry") or [{}])[0]
    change = (entry.get("changes") or [{}])[0]
    value = change.get("value", {})
    messages = value.get("messages") or []
    if not messages:
        return {"status": "ok"}

    msg = messages[0]
    from_number = msg.get("from", "")
    msg_text = ""
    if msg.get("type") == "text":
        msg_text = (msg.get("text") or {}).get("body", "")

    if not msg_text:
        return {"status": "ok"}

    # find matching active WhatsApp channel by phone number ID
    phone_id = (value.get("metadata") or {}).get("phone_number_id", "")
    async with db_session() as db:
        result = await db.execute(
            select(ChannelConnection).where(
                ChannelConnection.channel_type == "whatsapp",
                ChannelConnection.is_active == True,
            )
        )
        conn = None
        for ch in result.scalars():
            if ch.config.get("phone_id") == phone_id or phone_id == "":
                conn = ch
                break

        if not conn:
            logger.warning("No active WhatsApp channel to handle message")
            return {"status": "ok"}

        # resolve agent or team
        agent_or_team = None
        if conn.agent_id:
            agent_or_team = await db.get(Agent, conn.agent_id)
        elif conn.team_id:
            agent_or_team = await db.get(
                Team, conn.team_id, options=[selectinload(Team.agents)]
            )

        # find or create conversation by external_id
        ext_id = f"wa_{from_number}"
        conv = (await db.execute(
            select(Conversation).where(
                Conversation.channel == "whatsapp",
                Conversation.external_id == ext_id,
            )
        )).scalars().first()

        if not conv:
            conv = Conversation(
                org_id=conn.org_id,
                channel="whatsapp",
                external_id=ext_id,
                channel_connection_id=conn.id,
                agent_id=conn.agent_id,
                team_id=conn.team_id,
                extra_data={"from_number": from_number},
            )
            db.add(conv)
            await db.commit()
            await db.refresh(conv)

        # save inbound message
        db.add(Message(
            conversation_id=conv.id,
            role="user",
            content=msg_text,
            extra_data={"from_number": from_number},
        ))
        await db.commit()

        # check org limits
        allowed, reason = await check_org_limits(conn.org_id, db)
        if not allowed:
            logger.warning("WhatsApp limit hit for org %s: %s", conn.org_id, reason)
            return {"status": "ok"}

        # route to agent
        reply_text = None
        if agent_or_team:
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

                # send reply via WhatsApp
                ch = channel_mgr.build(conn, agent_or_team, db)
                await ch.send(OutboundMessage(
                    conversation_id=conv.id,
                    text=reply_text,
                    channel_connection_id=conn.id,
                    extra_data={"from_number": from_number},
                ))

    return {"status": "ok"}
