"""Storage manager — file upload, listing, retrieval for agents."""

import logging
import os
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aios.config import settings

logger = logging.getLogger(__name__)

STORAGE_DIR = Path(settings.app_data_dir) / "artifacts"


async def ensure_storage():
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def _store_path(org_id: str, filename: str) -> Path:
    """Generate unique storage path for an artifact."""
    ext = Path(filename).suffix
    name = f"{uuid.uuid4().hex}{ext}"
    org_dir = STORAGE_DIR / org_id
    org_dir.mkdir(parents=True, exist_ok=True)
    return org_dir / name


async def save_artifact(
    db: AsyncSession,
    org_id: str,
    filename: str,
    content: bytes,
    content_type: str = "application/octet-stream",
    conversation_id: str | None = None,
    agent_id: str | None = None,
    description: str = "",
) -> dict:
    """Save a file as an artifact and return its metadata."""
    from aios.db.models import Artifact

    path = _store_path(org_id, filename)
    path.write_bytes(content)

    art = Artifact(
        org_id=org_id,
        conversation_id=conversation_id,
        agent_id=agent_id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        storage_path=str(path.absolute()),
        description=description,
    )
    db.add(art)
    await db.commit()
    await db.refresh(art)
    return {
        "id": art.id,
        "filename": art.filename,
        "content_type": art.content_type,
        "size_bytes": art.size_bytes,
        "created_at": str(art.created_at),
    }


async def get_artifact_content(artifact_id: str, db: AsyncSession) -> bytes | None:
    """Read artifact file content from disk."""
    from aios.db.models import Artifact

    art = await db.get(Artifact, artifact_id)
    if not art:
        return None
    path = Path(art.storage_path)
    if not path.exists():
        logger.warning("Artifact file missing: %s", path)
        return None
    return path.read_bytes()


async def list_artifacts(
    db: AsyncSession,
    org_id: str,
    conversation_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List artifacts for an org, optionally filtered by conversation."""
    from aios.db.models import Artifact

    q = select(Artifact).where(Artifact.org_id == org_id).order_by(Artifact.created_at.desc()).limit(limit)
    if conversation_id:
        q = q.where(Artifact.conversation_id == conversation_id)
    result = await db.execute(q)
    return [
        {
            "id": a.id,
            "filename": a.filename,
            "content_type": a.content_type,
            "size_bytes": a.size_bytes,
            "description": a.description,
            "conversation_id": a.conversation_id,
            "created_at": str(a.created_at),
        }
        for a in result.scalars()
    ]


# ─── Agent Tool ───

READABLE_TYPES = {
    "text/plain", "text/html", "text/csv",
    "application/json", "application/xml",
    "application/pdf",  # handled separately
}
CODE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json", ".yaml", ".yml", ".md", ".txt", ".csv", ".xml", ".sql"}


async def read_artifact_text(artifact_id: str, db: AsyncSession, max_chars: int = 50000) -> str:
    """Read artifact content as text for agent tool consumption."""
    content = await get_artifact_content(artifact_id, db)
    if content is None:
        return "Error: artifact not found"

    # Try text decoding
    try:
        text = content.decode("utf-8")[:max_chars]
        return text
    except UnicodeDecodeError:
        return f"Binary file ({len(content)} bytes) — cannot display as text"
