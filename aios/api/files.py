"""File upload & artifact API."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query

from aios.api.ratelimit import limiter

from aios.core.file_validation import validate_file
from aios.core.storage import ensure_storage, list_artifacts, read_artifact_text, save_artifact
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Artifact
from .deps import get_current_user, get_org_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("/upload")
@limiter.limit("20/minute")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    conversation_id: str = Form(""),
    description: str = Form(""),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Upload a file as an artifact linked to a conversation."""
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 50MB)")

    # validate content type by magic bytes
    valid, content_type = validate_file(file.filename or "unnamed", content)
    if not valid:
        raise HTTPException(422, content_type)

    result = await save_artifact(
        db=db,
        org_id=org_id,
        filename=file.filename or "unnamed",
        content=content,
        content_type=content_type,
        conversation_id=conversation_id or None,
        description=description,
    )
    return result


@router.get("")
async def list_files(
    conversation_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """List artifacts for your org."""
    return await list_artifacts(db, org_id, conversation_id=conversation_id, limit=limit)


@router.get("/{artifact_id}/read")
async def read_file(
    artifact_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Read artifact content as text for agent use."""
    art = await db.get(Artifact, artifact_id)
    if not art or art.org_id != org_id:
        raise HTTPException(404)
    text = await read_artifact_text(artifact_id, db)
    return {"filename": art.filename, "content": text, "size_bytes": art.size_bytes}
