"""Email webhook — inbound emails from SendGrid/Mailgun/SES/AWS."""

import hashlib
import hmac
import logging

from fastapi import APIRouter, HTTPException, Request

from aios.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/email", tags=["email"])


def _verify_email_signature(request: Request, body: bytes, provider: str) -> bool:
    """Verify webhook signature based on provider."""
    secret_map = {
        "sendgrid": settings.sendgrid_webhook_secret,
        "mailgun": settings.mailgun_webhook_secret,
        "ses": settings.ses_webhook_secret,
    }
    secret = secret_map.get(provider)
    if not secret:
        return True  # No secret configured, skip

    sig = request.headers.get("x-twilio-email-event-webhook-signature", "")  # SendGrid
    if not sig:
        sig = request.headers.get("x-mailgun-signature", "")  # Mailgun
    if not sig:
        sig = request.headers.get("x-amz-sns-signature", "")  # SES/SNS

    if not sig:
        return False

    # Each provider has different signature format
    # Simplified: just HMAC-SHA256 of body
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


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
            message = json.loads(body.get("Message", "{}"))
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
    async with (await __import__("aios.db.backend", fromlist=["db_session"])).db_session() as db:
        from aios.db.models import ChannelConnection
        from sqlalchemy import select

        result = await db.execute(
            select(ChannelConnection).where(
                ChannelConnection.channel_type == "email",
                ChannelConnection.is_active == True,
            )
        )
        conn = result.scalars().first()

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


@router.get("/webhook")
async def email_webhook_verify():
    """Health check endpoint."""
    return {"status": "ok", "service": "email-webhook"}