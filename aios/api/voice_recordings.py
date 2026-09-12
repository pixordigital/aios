"""Voice recording management — list, search, download."""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func

from aios.core.audit import log_audit
from aios.core.storage import read_artifact_text, save_artifact
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import VoiceRecording, Conversation
from aios.schemas import PageResponse
from .deps import get_current_user, get_org_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice/recordings", tags=["voice-recordings"])


@router.get("", response_model=PageResponse[dict])
async def list_recordings(
    conversation_id: Optional[str] = Query(None),
    call_sid: Optional[str] = Query(None),
    from_number: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """List voice recordings with optional filters."""
    query = select(VoiceRecording).where(VoiceRecording.org_id == org_id)
    
    if conversation_id:
        query = query.where(VoiceRecording.conversation_id == conversation_id)
    if call_sid:
        query = query.where(VoiceRecording.call_sid == call_sid)
    if from_number:
        query = query.where(VoiceRecording.from_number.ilike(f"%{from_number}%"))
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            query = query.where(VoiceRecording.created_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            query = query.where(VoiceRecording.created_at <= dt_to)
        except ValueError:
            pass
    
    # Order by newest first
    query = query.order_by(VoiceRecording.created_at.desc()).limit(limit + 1).offset(offset)
    
    result = await db.execute(query)
    items = result.scalars().all()
    
    has_more = len(items) > limit
    if has_more:
        items = items[:limit]
    
    next_cursor = str(offset + limit) if has_more else None
    
    # Total count
    total_query = select(func.count(VoiceRecording.id)).where(VoiceRecording.org_id == org_id)
    if conversation_id:
        total_query = total_query.where(VoiceRecording.conversation_id == conversation_id)
    total = (await db.execute(total_query)).scalar() or 0
    
    return PageResponse(
        items=[{
            "id": r.id,
            "call_sid": r.call_sid,
            "conversation_id": r.conversation_id,
            "channel_connection_id": r.channel_connection_id,
            "from_number": r.from_number,
            "to_number": r.to_number,
            "direction": r.direction,
            "duration_seconds": r.duration_seconds,
            "recording_url": r.recording_url,
            "transcript_status": r.transcript_status,
            "transcript_language": r.transcript_language,
            "created_at": str(r.created_at),
        } for r in items],
        next_cursor=next_cursor,
        has_more=has_more,
        total=total,
    )


@router.get("/search")
async def search_recordings(
    q: str = Query(..., min_length=2, description="Search query for transcript content"),
    conversation_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Full-text search in voice recording transcripts."""
    from sqlalchemy import or_
    
    # Build search query using ILIKE for transcript content
    search_term = f"%{q}%"
    query = select(VoiceRecording).where(
        VoiceRecording.org_id == org_id,
        VoiceRecording.transcript.ilike(search_term)
    )
    
    if conversation_id:
        query = query.where(VoiceRecording.conversation_id == conversation_id)
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            query = query.where(VoiceRecording.created_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            query = query.where(VoiceRecording.created_at <= dt_to)
        except ValueError:
            pass
    
    query = query.order_by(VoiceRecording.created_at.desc()).limit(limit)
    
    result = await db.execute(query)
    items = result.scalars().all()
    
    return {
        "query": q,
        "results": [{
            "id": r.id,
            "call_sid": r.call_sid,
            "conversation_id": r.conversation_id,
            "from_number": r.from_number,
            "to_number": r.to_number,
            "direction": r.direction,
            "duration_seconds": r.duration_seconds,
            "transcript_snippet": _highlight_match(r.transcript or "", q),
            "transcript_status": r.transcript_status,
            "created_at": str(r.created_at),
        } for r in items],
        "count": len(items),
    }


def _highlight_match(text: str, query: str, context_chars: int = 100) -> str:
    """Return text snippet with query highlighted."""
    import re
    lower_text = text.lower()
    lower_query = query.lower()
    idx = lower_text.find(lower_query)
    if idx == -1:
        return text[:context_chars] + ("..." if len(text) > context_chars else "")
    
    start = max(0, idx - context_chars // 2)
    end = min(len(text), idx + len(query) + context_chars // 2)
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


@router.get("/{recording_id}")
async def get_recording(
    recording_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Get recording details with full transcript."""
    recording = await db.get(VoiceRecording, recording_id)
    if not recording or recording.org_id != org_id:
        raise HTTPException(404)
    
    return {
        "id": recording.id,
        "call_sid": recording.call_sid,
        "conversation_id": recording.conversation_id,
        "channel_connection_id": recording.channel_connection_id,
        "from_number": recording.from_number,
        "to_number": recording.to_number,
        "direction": recording.direction,
        "duration_seconds": recording.duration_seconds,
        "recording_url": recording.recording_url,
        "recording_storage_path": recording.recording_storage_path,
        "transcript": recording.transcript,
        "transcript_status": recording.transcript_status,
        "transcript_language": recording.transcript_language,
        "cost_usd": recording.cost_usd,
        "extra_data": recording.extra_data,
        "created_at": str(recording.created_at),
    }


@router.get("/{recording_id}/audio")
async def download_recording_audio(
    recording_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Download recording audio file."""
    from fastapi.responses import StreamingResponse
    from aios.core.storage import backend
    
    recording = await db.get(VoiceRecording, recording_id)
    if not recording or recording.org_id != org_id:
        raise HTTPException(404)
    
    if not recording.recording_storage_path:
        raise HTTPException(404, "Audio file not available")
    
    content = await backend().read(recording.recording_storage_path)
    if not content:
        raise HTTPException(404, "Audio file not found in storage")
    
    return StreamingResponse(
        iter([content]),
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'attachment; filename="recording-{recording.call_sid}.mp3"'}
    )


@router.post("/{recording_id}/transcribe")
async def transcribe_recording(
    recording_id: str,
    language: str = Query("pt"),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Trigger transcription for a recording using Whisper."""
    recording = await db.get(VoiceRecording, recording_id)
    if not recording or recording.org_id != org_id:
        raise HTTPException(404)
    
    if not recording.recording_storage_path:
        raise HTTPException(400, "No audio file to transcribe")
    
    recording.transcript_status = "processing"
    await db.commit()
    
    # Queue transcription job
    from aios.tasks.queue import enqueue_job
    await enqueue_job(
        "transcribe_voice_recording",
        recording_id=recording_id,
        language=language,
    )
    
    await log_audit(db, org_id, "voice.recording.transcribe", "voice_recording",
                   user_id=user.id, resource_id=recording_id,
                   details={"language": language})
    
    return {"status": "queued", "recording_id": recording_id}