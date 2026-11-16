"""Postgres pgvector store for long-term memory.

The per-agent SQLite files in `data/vectors/` only work when every replica sees
the same filesystem and only one process writes them. Production runs several
containers, so memories written by a worker were invisible to the API, and a
shared volume would put SQLite on a network filesystem. This table is the
multi-replica store; SQLite stays the dev/test backend.

`memory_vectors` lives outside `Base.metadata` on purpose: it only exists on
Postgres, and creating it on SQLite would give the dev fallback a second,
unused copy of the same data. See alembic revision c2d3e4f5a6b7.
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from aios.config import settings

logger = logging.getLogger(__name__)

_TABLE = "memory_vectors"


def use_postgres() -> bool:
    """Pick the store. `AIOS_VECTOR_BACKEND=sqlite` is the rollback switch."""
    backend = (settings.vector_backend or "auto").strip().lower()
    if backend == "sqlite":
        return False
    if backend == "postgres":
        return True
    from aios.db.engine import engine

    return engine.dialect.name.startswith("postgres")


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.7f}" for v in vec) + "]"


def _session():
    from aios.db.engine import async_session

    return async_session()


async def store(agent_id: str, org_id: str, content: str, embedding: list[float]) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with _session() as session:
        await session.execute(
            text(
                f"INSERT INTO {_TABLE} (id, org_id, agent_id, content, embedding, created_at)"
                " VALUES (:id, :org, :agent, :content, CAST(:emb AS vector), :created_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "org": org_id,
                "agent": agent_id,
                "content": content,
                "emb": _vec_literal(embedding),
                "created_at": now,
            },
        )
        await session.commit()


async def similar(
    agent_id: str, org_id: str, embedding: list[float], top_k: int = 5
) -> list[dict]:
    async with _session() as session:
        rows = await session.execute(
            text(
                f"SELECT id, content, 1 - (embedding <=> CAST(:emb AS vector)) AS score"
                f" FROM {_TABLE} WHERE agent_id = :agent AND org_id = :org"
                " ORDER BY embedding <=> CAST(:emb AS vector) LIMIT :k"
            ),
            {"emb": _vec_literal(embedding), "agent": agent_id, "org": org_id, "k": top_k},
        )
        return [
            {"id": r.id, "content": r.content, "score": round(float(r.score), 3)}
            for r in rows
        ]


async def fts(agent_id: str, org_id: str, query: str, top_k: int = 5) -> list[dict]:
    """Full-text search. `simple` config has no stemming, unlike SQLite FTS5."""
    async with _session() as session:
        rows = await session.execute(
            text(
                f"SELECT id, content, ts_rank_cd(content_tsv, plainto_tsquery('simple', :q)) AS score"
                f" FROM {_TABLE} WHERE agent_id = :agent AND org_id = :org"
                " AND content_tsv @@ plainto_tsquery('simple', :q)"
                " ORDER BY score DESC LIMIT :k"
            ),
            {"q": query, "agent": agent_id, "org": org_id, "k": top_k},
        )
        return [
            {"id": r.id, "content": r.content, "score": round(float(r.score), 3)}
            for r in rows
        ]


async def sa_cts(
    agent_id: str, org_id: str, embedding: list[float], top_k: int = 5
) -> list[dict]:
    """similarity * recency * importance, same weights as the SQLite store."""
    async with _session() as session:
        rows = await session.execute(
            text(
                f"SELECT id, content, embedding::text AS emb, created_at FROM {_TABLE}"
                " WHERE agent_id = :agent AND org_id = :org"
                " ORDER BY created_at DESC LIMIT 100"
            ),
            {"agent": agent_id, "org": org_id},
        )
        rows = rows.all()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    scored = []
    for r in rows:
        try:
            stored = [float(v) for v in r.emb.strip("[]").split(",") if v]
            sim = sum(a * b for a, b in zip(embedding, stored))
            age_hours = (now - r.created_at).total_seconds() / 3600
            recency = math.exp(-age_hours / 24)
            imp = 1.3 if r.content.startswith("[skill]") else 1.1 if r.content.startswith("[fact]") else 1.0
            scored.append((sim * 0.6 + recency * 0.2 + (imp - 1.0) * 0.2, r.id, r.content))
        except Exception:
            continue
    scored.sort(key=lambda x: -x[0])
    return [{"id": r[1], "content": r[2], "score": round(r[0], 3)} for r in scored[:top_k]]


async def recent(agent_id: str, org_id: str, top_k: int = 10) -> list[dict]:
    async with _session() as session:
        rows = await session.execute(
            text(
                f"SELECT id, content, created_at FROM {_TABLE}"
                " WHERE agent_id = :agent AND org_id = :org"
                " ORDER BY created_at DESC LIMIT :k"
            ),
            {"agent": agent_id, "org": org_id, "k": top_k},
        )
        return [
            {
                "id": r.id,
                "content": r.content,
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
            for r in rows
        ]


async def update_used(memory_id: str, success: bool) -> None:
    """RL signal. Success also refreshes recency, matching the SQLite store."""
    async with _session() as session:
        await session.execute(
            text(
                f"UPDATE {_TABLE} SET usage_count = usage_count + 1,"
                " success_count = success_count + :inc, last_used = :now"
                + (", created_at = :now" if success else "")
                + " WHERE id = :id"
            ),
            {
                "inc": 1 if success else 0,
                "now": datetime.now(timezone.utc).replace(tzinfo=None),
                "id": memory_id,
            },
        )
        await session.commit()


async def discard(memory_id: str) -> bool:
    """Delete a memory that has proven useless; returns True when deleted."""
    async with _session() as session:
        result = await session.execute(
            text(
                f"DELETE FROM {_TABLE} WHERE id = :id AND"
                " ((usage_count >= 10 AND success_count::float / usage_count < 0.3)"
                " OR length(content) < 20)"
            ),
            {"id": memory_id},
        )
        await session.commit()
        return bool(result.rowcount)
