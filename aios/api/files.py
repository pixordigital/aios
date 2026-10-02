"""File upload & artifact API."""

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query

from aios.api.ratelimit import limiter

from aios.core.file_validation import validate_file
from aios.core.storage import list_artifacts, read_artifact_text, save_artifact
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Artifact
from .deps import get_current_user, get_org_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files", tags=["files"])

# Max upload size: 10MB (hardened from 50MB per security review)
MAX_UPLOAD_SIZE = 10 * 1024 * 1024


async def scan_with_clamav(content: bytes) -> tuple[bool, str]:
    """Scan file content with ClamAV daemon.
    Returns (is_clean, details). If ClamAV not available, returns (True, "clamav not configured").
    """
    import socket
    import os
    
    clamav_host = os.getenv("CLAMAV_HOST", "localhost")
    clamav_port = int(os.getenv("CLAMAV_PORT", "3310"))
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect((clamav_host, clamav_port))
        
        # Send INSTREAM command
        sock.send(b"zINSTREAM\0")
        
        # Send file content in chunks
        chunk_size = 1024
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            sock.send(len(chunk).to_bytes(4, 'big') + chunk)
        
        # Send zero-length chunk to end stream
        sock.send(b"\0\0\0\0")
        
        # Read response
        response = b""
        while True:
            data = sock.recv(1024)
            if not data:
                break
            response += data
        
        sock.close()
        response_str = response.decode('utf-8', errors='ignore')
        
        if "FOUND" in response_str:
            logger.warning("ClamAV detected threat: %s", response_str)
            return False, f"Malware detected: {response_str}"
        elif "OK" in response_str:
            return True, "Clean"
        else:
            logger.warning("ClamAV unexpected response: %s", response_str)
            return True, f"Unknown response: {response_str}"
            
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        logger.debug("ClamAV not available: %s", e)
        return True, "ClamAV not available"
    except Exception as e:
        logger.warning("ClamAV scan error: %s", e)
        return True, f"Scan error: {e}"


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
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(413, f"Arquivo muito grande (máx. {MAX_UPLOAD_SIZE // (1024*1024)}MB)")

    # validate content type by magic bytes
    valid, content_type = validate_file(file.filename or "unnamed", content)
    if not valid:
        raise HTTPException(422, content_type)

    # ClamAV malware scan
    clamav_enabled = os.getenv("CLAMAV_ENABLED", "false").lower() == "true"
    if clamav_enabled:
        is_clean, details = await scan_with_clamav(content)
        if not is_clean:
            logger.warning("File upload blocked by ClamAV: %s (org=%s, user=%s)", details, org_id, user.id)
            raise HTTPException(422, f"Arquivo rejeitado: {details}")

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
