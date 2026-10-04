"""Voice webhook — Twilio inbound call events."""

import base64
import hashlib
import hmac
import logging
from urllib.parse import parse_qsl, urlparse, urlunsplit

from fastapi import APIRouter, HTTPException, Request

from aios.config import settings
from aios.db.backend import db_session
from aios.db.models import VoiceRecording
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])


def _verify_twilio_signature(request: Request, body: bytes) -> bool:
    """Validate Twilio's real signature scheme.

    Twilio sends `X-Twilio-Signature` = base64(HMAC-SHA1(auth_token,
    full_url + sorted POST params)). The endpoint instead required an
    `x-voice-signature` header holding hex(HMAC-SHA256(secret, body)) — a
    header no provider emits and a construction none uses — so every genuine
    call event 401'd while voice was listed in the Pro plan.

    `AIOS_VOICE_WEBHOOK_SECRET` is read as the Twilio auth token.
    """
    header = request.headers.get("x-twilio-signature", "")
    if not header:
        logger.warning("Twilio webhook missing X-Twilio-Signature")
        return False
    token = settings.voice_webhook_secret.encode()

    url = str(request.url)
    # Twilio signs the URL with any query string removed, then each POST field
    # name concatenated with its value, both sorted.
    parsed = urlparse(url)
    url_without_query = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    fields: list[str] = []
    if request.query_params:
        for k, v in request.query_params.items():
            fields.append(k + v)
    if body:
        try:
            form = dict(parse_qsl(body.decode("utf-8", "replace"), keep_blank_values=True))
            for k, v in form.items():
                fields.append(k + v)
        except Exception:
            logger.debug("Twilio body is not form-encoded", exc_info=True)

    payload = (url_without_query + "".join(sorted(fields))).encode()
    expected = base64.b64encode(
        hmac.new(token, payload, hashlib.sha1).digest()
    ).decode()
    return hmac.compare_digest(header, expected)


def _twilio_form_to_body(form) -> dict:
    """Normalize Twilio's form fields into this webhook's vocabulary.

    Twilio sends CallSid/From/To/CallStatus/RecordingUrl; the handler below
    speaks call.started/call.ended/recording.completed with snake_case fields.
    Mapping is conservative: only statuses with an unambiguous equivalent set
    `event`, everything else keeps the raw fields so the recording branches can
    still match on call_sid.
    """
    get = lambda k, default="": (form.get(k) or default)  # noqa: E731
    body = {
        "call_sid": get("CallSid"),
        "from": get("From", get("Caller")),
        "to": get("To", get("Called")),
        "channel_id": get("channel_id"),
        "duration": get("RecordingDuration", get("CallDuration", get("Duration"))),
        "recording_url": get("RecordingUrl"),
    }
    status = (get("CallStatus") or "").lower()
    if status in ("in-progress", "ringing", "queued"):
        body["event"] = "call.started"
    elif status in ("completed", "busy", "failed", "no-answer", "canceled"):
        body["event"] = "call.ended"
    elif get("RecordingUrl"):
        body["event"] = "recording.completed"
    elif get("event"):
        body["event"] = get("event")
    # Twilio recording callbacks carry no explicit event; the presence of a
    # recording URL on a completed call is the signal.
    if not body.get("event") and body.get("recording_url"):
        body["event"] = "recording.completed"
    return {k: v for k, v in body.items() if v not in ("", None, 0, {})}


@router.post("/webhook")
async def voice_webhook(request: Request):
    """Receive voice events from Twilio → dispatch to agent."""
    raw_body = await request.body()

    # Verify signature. Fail CLOSED: when no secret is configured the old code
    # skipped verification entirely, so anyone could post forged Twilio events
    # and trigger agent runs (and bill usage) for any tenant.
    if not settings.voice_webhook_secret:
        logger.error("Voice webhook called with no voice_webhook_secret configured")
        raise HTTPException(
            503, "Voice webhook secret not configured; refusing unauthenticated webhook"
        )
    if not _verify_twilio_signature(request, raw_body):
        logger.warning("Voice webhook signature rejected")
        raise HTTPException(401, "Invalid signature")

    # Twilio posts application/x-www-form-urlencoded with PascalCase fields,
    # not the JSON vocabulary below. Reading only json() made every real Twilio
    # callback parse to {} and fall through silently — authenticated but inert.
    body: dict = {}
    content_type = (request.headers.get("content-type") or "").lower()
    if "form-" in content_type or "urlencoded" in content_type:
        try:
            form = await request.form()
            body = _twilio_form_to_body(form)
        except Exception:
            logger.warning("voice webhook: form parse failed", exc_info=True)
            body = {}
    else:
        try:
            parsed = await request.json()
            body = parsed if isinstance(parsed, dict) else {}
        except Exception:
            body = {}

    event = body.get("event", "")
    call_sid = body.get("call_sid", body.get("call", {}).get("sid", ""))

    # Handle different event types
    if event in ("call.started", "call.incoming"):
        # Dispatch to agent for handling
        from aios.core.dispatch import dispatch_inbound

        from_number = body.get("from", body.get("caller_id", ""))
        to_number = body.get("to", body.get("called_number", ""))

        async with db_session() as db:
            from aios.db.models import ChannelConnection

            # Same tenant-mixing defect as the email webhook: `.first()` picked
            # an arbitrary tenant's voice connection.
            q = select(ChannelConnection).where(
                ChannelConnection.channel_type == "voice",
                ChannelConnection.is_active == True,
            )
            if body.get("channel_id"):
                q = q.where(ChannelConnection.id == str(body["channel_id"]))
            candidates = (await db.execute(q.limit(2))).scalars().all()
            conn = candidates[0] if candidates else None
            if conn is not None and not body.get("channel_id") and len(candidates) > 1:
                return {"ok": False,
                        "error": "more than one active voice channel; pass channel_id"}

            if conn:
                # Create voice recording entry
                recording = VoiceRecording(
                    org_id=conn.org_id,
                    call_sid=call_sid,
                    channel_connection_id=conn.id,
                    from_number=from_number,
                    to_number=to_number,
                    direction="inbound",
                    duration_seconds=0,
                    transcript_status="pending",
                )
                db.add(recording)
                await db.commit()

                await dispatch_inbound(
                    channel_type="voice",
                    channel_connection_id=conn.id,
                    conversation_id="",
                    text=f"Incoming call from {from_number} to {to_number}",
                    user_id=from_number,
                    extra_data={
                        "event": event,
                        "call_sid": call_sid,
                        "from_number": from_number,
                        "to_number": to_number,
                        "direction": "inbound",
                        "recording_id": recording.id,
                    },
                )

    elif event in ("call.ended", "call.completed"):
        logger.info("Call ended: %s", call_sid)
        
        # Update recording with duration and recording URL
        async with db_session() as db:
            recording_result = await db.execute(
                select(VoiceRecording).where(VoiceRecording.call_sid == call_sid)
            )
            recording = recording_result.scalar_one_or_none()
            
            if recording:
                recording.duration_seconds = body.get("duration", 0) or body.get("call_duration", 0)
                recording.recording_url = body.get("recording_url") or body.get("recording", {}).get("url")
                recording.extra_data = {**(recording.extra_data or {}), "end_event": body}
                await db.commit()
                
                # If recording URL available, could download and store
                if recording.recording_url:
                    # Queue download job
                    from aios.tasks.queue import enqueue_job
                    await enqueue_job(
                        "download_voice_recording",
                        recording_id=recording.id,
                        recording_url=recording.recording_url,
                    )

    elif event == "recording.completed":
        # Twilio recording completed event
        recording_url = body.get("recording_url") or body.get("recording", {}).get("url")
        duration = body.get("duration", 0)
        
        async with db_session() as db:
            recording_result = await db.execute(
                select(VoiceRecording).where(VoiceRecording.call_sid == call_sid)
            )
            recording = recording_result.scalar_one_or_none()
            
            if recording:
                recording.recording_url = recording_url
                recording.duration_seconds = duration
                await db.commit()
                
                # Queue download
                from aios.tasks.queue import enqueue_job
                await enqueue_job(
                    "download_voice_recording",
                    recording_id=recording.id,
                    recording_url=recording_url,
                )

    return {"status": "ok"}


@router.get("/webhook")
async def voice_webhook_verify():
    """Health check / verification endpoint."""
    return {"status": "ok", "service": "voice-webhook"}