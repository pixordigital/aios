"""Voice webhook — LiveKit / Twilio inbound call events."""

import hashlib
import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from aios.config import settings
from aios.db.models import VoiceRecording
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.post("/webhook")
async def voice_webhook(request: Request):
    """Receive voice events from LiveKit/Twilio → dispatch to agent."""
    raw_body = await request.body()

    # Verify signature if configured
    if settings.voice_webhook_secret:
        sig = request.headers.get("x-voice-signature", "")
        if not sig:
            logger.warning("Voice webhook missing signature")
            raise HTTPException(401, "Missing signature")
        expected = hmac.new(
            settings.voice_webhook_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            logger.warning("Voice webhook signature mismatch")
            raise HTTPException(401, "Invalid signature")

    try:
        body = await request.json()
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

        async with (await __import__("aios.db.backend", fromlist=["db_session"])).db_session() as db:
            from aios.db.models import ChannelConnection

            result = await db.execute(
                select(ChannelConnection).where(
                    ChannelConnection.channel_type == "voice",
                    ChannelConnection.is_active == True,
                )
            )
            conn = result.scalars().first()

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
        async with (await __import__("aios.db.backend", fromlist=["db_session"])).db_session() as db:
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
        # Twilio/ LiveKit recording completed event
        recording_url = body.get("recording_url") or body.get("recording", {}).get("url")
        duration = body.get("duration", 0)
        
        async with (await __import__("aios.db.backend", fromlist=["db_session"])).db_session() as db:
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