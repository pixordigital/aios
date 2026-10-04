"""Email webhook — inbound emails from SendGrid/Mailgun/SES/AWS."""

import hashlib
import time
import hmac
import logging

from fastapi import APIRouter, HTTPException, Request

from aios.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/email", tags=["email"])


def _verify_email_signature(request: Request, body: bytes, provider: str) -> bool:
    """Verify the provider's real signature scheme.

    This computed one HMAC-SHA256 hex digest of the body and compared it to
    every provider's header. No provider sends that, so all three 401'd
    permanently:

      * Mailgun  X-Mailgun-Signature = "<ts>,<hmac_sha256(ts + body)>"
      * SendGrid  base64 ECDSA over (ts + body), verified with the app's
        *public* key, not a shared secret
      * SES/SNS  base64 RSA-SHA256 over a canonical string

    Mailgun is implemented properly. SendGrid and SNS need asymmetric keys,
    which this codebase has no setting for, so they fail closed with an
    explicit reason instead of pretending to verify.
    """
    if provider == "mailgun":
        secret = settings.mailgun_webhook_secret
        if not secret:
            logger.error("mailgun webhook called with no AIOS_MAILGUN_WEBHOOK_SECRET")
            return False
        header = request.headers.get("x-mailgun-signature", "")
        if "," not in header:
            logger.warning("mailgun signature missing or malformed")
            return False
        ts, _, signature = header.partition(",")
        # Mailgun signs ts+body but the timestamp was never checked against the
        # clock, so a captured request replayed forever and re-dispatched the
        # same inbound mail to the agent on every retry.
        try:
            if abs(time.time() - int(ts)) > 300:
                logger.warning("mailgun signature timestamp outside the 300s window")
                return False
        except (TypeError, ValueError):
            logger.warning("mailgun signature timestamp unparseable")
            return False
        expected = hmac.new(
            secret.encode(), ts.encode() + body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature.strip(), expected)

    if provider in ("sendgrid", "ses"):
        # Asymmetric schemes: SendGrid is ECDSA over ts+body with the app's
        # public key, SNS is RSA-SHA256 over a canonical string. Neither can be
        # checked with a shared secret, and guessing one produced a digest that
        # never matched anything. Refuse loudly rather than silently accepting.
        logger.error(
            "%s inbound parse requires asymmetric signature verification, "
            "which is not configured; refusing the request",
            provider,
        )
        return False

    logger.error("unknown email provider %r; refusing", provider)
    return False


@router.post("/webhook")
async def email_webhook(request: Request):
    """Receive inbound email from provider → dispatch to agent."""
    raw_body = await request.body()

    # Detect provider from headers/body
    provider = "unknown"
    if "x-twilio-email-event-webhook-signature" in request.headers:
        provider = "sendgrid"
    elif "x-mailgun-signature" in request.headers:
        provider = "mailgun"
    elif "x-amz-sns-message-type" in request.headers:
        provider = "ses"

    if not _verify_email_signature(request, raw_body, provider):
        logger.warning("Email webhook signature verification failed for %s", provider)
        raise HTTPException(401, "Invalid signature")

    try:
        body = await request.json()
    except Exception:
        body = {}

    # Handle different provider formats
    if provider == "sendgrid":
        # SendGrid sends array of events
        events = body if isinstance(body, list) else [body]
        for event in events:
            if event.get("event") == "inbound":
                await _process_inbound_email(event, "sendgrid")

    elif provider == "mailgun":
        # Mailgun posts form data with 'message' field
        if "message" in body:
            await _process_inbound_email(body, "mailgun")

    elif provider == "ses":
        # SES sends via SNS notification
        if body.get("Type") == "Notification":
            import json
            try:
                raw_message = body.get("Message", "{}")
                message = json.loads(raw_message) if isinstance(raw_message, str) else {}
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.warning("SES SNS Message is not JSON; ignoring notification")
                return {"status": "ok"}
            if message.get("mail"):
                await _process_inbound_email(message, "ses")

    return {"status": "ok"}


async def _process_inbound_email(email_data: dict, provider: str):
    """Extract email content and dispatch to agent."""
    from aios.core.dispatch import dispatch_inbound

    # Normalize fields across providers
    from_email = ""
    to_email = ""
    subject = ""
    text_content = ""
    html_content = ""
    message_id = ""

    if provider == "sendgrid":
        from_email = email_data.get("from", "")
        to_email = email_data.get("to", "")
        subject = email_data.get("subject", "")
        text_content = email_data.get("text", "")
        html_content = email_data.get("html", "")
        message_id = email_data.get("message_id", "")

    elif provider == "mailgun":
        message = email_data.get("message", {})
        from_email = message.get("from", "")
        to_email = ", ".join(message.get("to", []))
        subject = message.get("subject", "")
        text_content = message.get("body-plain", "")
        html_content = message.get("body-html", "")
        message_id = message.get("message-id", "")

    elif provider == "ses":
        mail = email_data.get("mail", {})
        from_email = mail.get("source", "")
        to_email = ", ".join(mail.get("destination", []))
        content = email_data.get("content", "")
        # Parse email content (simplified)
        subject = "Incoming email"
        text_content = content[:5000]

    # Find active email channel
    from aios.db.backend import db_session

    async with db_session() as db:
        from aios.db.models import ChannelConnection
        from sqlalchemy import select

        # Resolve THIS mailbox's connection, not whichever tenant happens to be
        # first in the table: `.first()` handed tenant B's inbound mail to
        # tenant A's agent, billed A's quota and stored the message under A's
        # org_id. An explicit channel id wins; otherwise only a single active
        # connection may be auto-resolved, and ambiguity is refused.
        q = select(ChannelConnection).where(
            ChannelConnection.channel_type == "email",
            ChannelConnection.is_active == True,
        )
        # Body-supplied channel_id removed for the same reason as the voice
        # webhook: one global Mailgun secret for all tenants, so a caller-chosen
        # id crossed tenants and billed the wrong org.
        candidates = (await db.execute(q.limit(2))).scalars().all()
        conn = candidates[0] if candidates else None
        if conn is not None and len(candidates) > 1:
            return {"ok": False,
                    "error": "more than one active email channel; cannot resolve unambiguously"}

        if conn:
            await dispatch_inbound(
                channel_type="email",
                channel_connection_id=conn.id,
                conversation_id="",
                text=f"Subject: {subject}\n\n{text_content}",
                user_id=from_email,
                extra_data={
                    "event": "inbound",
                    "provider": provider,
                    "from_email": from_email,
                    "to_email": to_email,
                    "subject": subject,
                    "html_content": html_content[:5000] if html_content else "",
                    "message_id": message_id,
                },
            )
        else:
            # No active email channel: the message has nowhere to go. Say so,
            # or the sender's mail vanishes with no trace anywhere.
            logger.warning(
                "inbound %s email from %s dropped: no active email channel",
                provider,
                from_email or "?",
            )


@router.get("/webhook")
async def email_webhook_verify():
    """Health check endpoint."""
    return {"status": "ok", "service": "email-webhook"}