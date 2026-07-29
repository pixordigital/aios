"""Storage manager — file upload, listing, retrieval for agents.

Supports local filesystem and S3-compatible backends (Supabase Storage, R2, MinIO).
"""

import logging
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from sqlalchemy import select

from aios.config import settings
from aios.db.backend import DatabaseBackend

logger = logging.getLogger(__name__)

STORAGE_DIR = Path(settings.app_data_dir) / "artifacts"


# ─── Storage Backends ───


class StorageBackend(ABC):
    """Abstract storage backend."""

    @abstractmethod
    async def save(self, org_id: str, filename: str, content: bytes) -> str:
        """Save content, return storage path/key."""
        ...

    @abstractmethod
    async def read(self, path: str) -> bytes | None:
        """Read content from storage path."""
        ...

    @abstractmethod
    async def delete(self, path: str) -> bool:
        """Delete content. Returns True if existed."""
        ...


class LocalStorage(StorageBackend):
    """Local filesystem storage."""

    async def save(self, org_id: str, filename: str, content: bytes) -> str:
        ext = Path(filename).suffix
        name = f"{uuid.uuid4().hex}{ext}"
        org_dir = STORAGE_DIR / org_id
        org_dir.mkdir(parents=True, exist_ok=True)
        path = org_dir / name
        path.write_bytes(content)
        return str(path.absolute())

    async def read(self, path: str) -> bytes | None:
        p = Path(path)
        if not p.exists():
            return None
        return p.read_bytes()

    async def delete(self, path: str) -> bool:
        p = Path(path)
        if not p.exists():
            return False
        p.unlink()
        return True


class S3Storage(StorageBackend):
    """S3-compatible storage (Supabase Storage, Cloudflare R2, MinIO)."""

    def __init__(self):
        self._client = None
        self._bucket = settings.s3_bucket
        self._endpoint = settings.s3_endpoint
        self._region = settings.s3_region

    async def _get_client(self):
        if self._client is None:
            try:
                import aioboto3
            except ImportError:
                raise RuntimeError("S3 storage requires aioboto3: pip install aioboto3")

            session = aioboto3.Session()
            self._client = await session.client(
                "s3",
                endpoint_url=self._endpoint or None,
                region_name=self._region or "auto",
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=settings.s3_secret_key,
            ).__aenter__()
        return self._client

    async def save(self, org_id: str, filename: str, content: bytes) -> str:
        client = await self._get_client()
        ext = Path(filename).suffix
        key = f"{org_id}/{uuid.uuid4().hex}{ext}"
        await client.put_object(Bucket=self._bucket, Key=key, Body=content)
        logger.info("Saved s3://%s/%s (%d bytes)", self._bucket, key, len(content))
        return key

    async def read(self, path: str) -> bytes | None:
        client = await self._get_client()
        try:
            resp = await client.get_object(Bucket=self._bucket, Key=path)
            return await resp["Body"].read()
        except client.exceptions.NoSuchKey:
            return None

    async def delete(self, path: str) -> bool:
        client = await self._get_client()
        try:
            await client.delete_object(Bucket=self._bucket, Key=path)
            return True
        except Exception:
            logger.exception("S3 delete failed for %s", path)
            return False


def _get_backend() -> StorageBackend:
    if settings.storage_backend == "s3":
        return S3Storage()
    return LocalStorage()


_backend = None


def backend() -> StorageBackend:
    global _backend
    if _backend is None:
        _backend = _get_backend()
    return _backend


# ─── Init ───


async def ensure_storage():
    if settings.storage_backend == "local":
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Storage backend: %s", settings.storage_backend)


# ─── Artifact CRUD ───


async def save_artifact(
    db: DatabaseBackend,
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

    storage_path = await backend().save(org_id, filename, content)

    art = Artifact(
        org_id=org_id,
        conversation_id=conversation_id,
        agent_id=agent_id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        storage_path=storage_path,
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


async def get_artifact_content(artifact_id: str, db: DatabaseBackend) -> bytes | None:
    """Read artifact file content from backend."""
    from aios.db.models import Artifact

    art = await db.get(Artifact, artifact_id)
    if not art:
        return None
    return await backend().read(art.storage_path)


async def list_artifacts(
    db: DatabaseBackend,
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


async def read_artifact_text(artifact_id: str, db: DatabaseBackend, max_chars: int = 50000) -> str:
    """Read artifact content as text for agent tool consumption."""
    content = await get_artifact_content(artifact_id, db)
    if content is None:
        return "Error: artifact not found"

    try:
        text = content.decode("utf-8")[:max_chars]
        return text
    except UnicodeDecodeError:
        return f"Binary file ({len(content)} bytes) — cannot display as text"
