"""Telegram webhook — inbound updates from the Bot API.

Active only when `public_base_url` and `telegram_webhook_secret` are set; the
channel calls setWebhook in that case and skips its poll loop. Telegram echoes
the secret in X-Telegram-Bot-Api-Secret-Token, which is how an update is proven
to come from Telegram and not from anyone who knows the URL.
"""

import hmac
import logging

from fastapi import APIRouter, HTTPException, Request

from aios.config import settings
from aios.db.backend import db_session
from aios.db.models import ChannelConnection
from aios.governance.security import record_auth_failure

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telegram", tags=["telegram"])

_SECRET_HEADER = "x-telegram-bot-api-secret-token"


def _expected_secret(conn: ChannelConnection | None) -> str:
    if conn is not None:
        per_conn = (conn.config or {}).get("webhook_secret", "")
        if per_conn:
            return per_conn
    return settings.telegram_webhook_secret


@router.post("/webhook/{connection_id}")
async def telegram_webhook(connection_id: str, request: Request):
    """Receive a Telegram update → dispatch to the ARQ worker."""
    header = request.headers.get(_SECRET_HEADER, "")
    try:
        body = await request.json()
    except Exception:
        body = {}

    async with db_session() as db:
        conn = await db.get(ChannelConnection, connection_id)
        secret = _expected_secret(conn)

        # Fail CLOSED. With no secret configured, anyone who finds the URL could
        # inject messages into a tenant's agent.
        if not secret:
            if conn and conn.org_id:
                try:
                    await record_auth_failure(
                        db,
                        org_id=conn.org_id,
                        source="api.telegram.webhook",
                        severity="medium",
                        actor_type="external",
                        payload={"reason": "missing_webhook_secret", "connection_id": connection_id},
                    )
                    await db.commit()
                except Exception:
                    logger.debug("telegram security event skipped", exc_info=True)
            raise HTTPException(503, "Telegram webhook secret not configured")
        if not header or not hmac.compare_digest(header, secret):
            if conn and conn.org_id:
                try:
                    await record_auth_failure(
                        db,
                        org_id=conn.org_id,
                        source="api.telegram.webhook",
                        severity="medium",
                        actor_type="external",
                        payload={"reason": "invalid_secret_token", "connection_id": connection_id},
                    )
                    await db.commit()
                except Exception:
                    logger.debug("telegram security event skipped", exc_info=True)
            logger.warning("Telegram webhook auth failed for connection %s", connection_id)
            raise HTTPException(401, "Invalid secret token")

    if conn is None or conn.channel_type != "telegram" or not conn.is_active:
        # Authenticated, but nothing to route to. 200 so Telegram stops retrying.
        return {"ok": True}

    msg = body.get("message") or {}
    chat = msg.get("chat") or {}
    text = msg.get("text") or ""
    if not text or not chat.get("id"):
        return {"ok": True}

    from aios.core.dispatch import dispatch_inbound
    from aios.core.owner_notify import ack_notification

    await ack_notification(conn.org_id, "telegram", "telegram")
    await dispatch_inbound(
        channel_type="telegram",
        channel_connection_id=conn.id,
        conversation_id="",
        text=text,
        user_id=str((msg.get("from") or {}).get("id", "")),
        extra_data={
            "chat_id": chat["id"],
            "message_id": msg.get("message_id"),
            # Same shape as the poll loop, so process_inbound dedups both paths
            # by channel_message_id on a Telegram redelivery.
            "msg_id": f"telegram:{chat['id']}:{msg.get('message_id')}",
            "chat_type": chat.get("type"),
            "username": (msg.get("from") or {}).get("username"),
        },
    )
    return {"ok": True}
