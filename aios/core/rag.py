import json as _json
import logging

from sqlalchemy import select, text

from aios.db.engine import async_session
from aios.governance.knowledge import (
    KnowledgeRecord,
    can_retrieve,
    knowledge_citation,
    knowledge_text_score,
)

logger = logging.getLogger(__name__)


RAG_STATUS = {"vector": False, "hnsw": False, "fallback": True}

async def ensure_vector_extension():
    global RAG_STATUS
    try:
        async with async_session() as s:
            await s.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await s.commit()
            RAG_STATUS["vector"] = True
            try:
                from aios.core import vector_store

                if vector_store.use_postgres():
                    # The index is created by the migration; report it only if
                    # it actually exists, so /health does not claim pgvector
                    # readiness on a database that has not been upgraded.
                    reg = await s.execute(
                        text("SELECT to_regclass('ix_memory_vectors_embedding')")
                    )
                    RAG_STATUS["hnsw"] = reg.scalar() is not None
                else:
                    RAG_STATUS["hnsw"] = False
                RAG_STATUS["fallback"] = not RAG_STATUS["hnsw"]
                logger.info(
                    "vector extension ready; memory hnsw index %s",
                    "present" if RAG_STATUS["hnsw"] else "absent",
                )
            except Exception as e:
                logger.warning("pgvector HNSW index check failed, fallback sqlite: %s", e)
                RAG_STATUS["fallback"] = True
    except Exception as e:
        logger.warning("vector extension not available, RAG fallback sqlite: %s", e)
        RAG_STATUS["vector"] = False
        RAG_STATUS["fallback"] = True


def _knowledge_hit(record: KnowledgeRecord, score: float) -> dict:
    return {
        "id": record.id,
        "record_id": record.id,
        "title": record.title,
        "content": (record.content or "")[:600],
        "score": round(float(score), 4),
        "source": "knowledge_record",
        "kind": record.kind,
        "classification": record.classification,
        "department_id": record.department_id,
        "source_type": record.source_type,
        "source_id": record.source_id,
        "provenance": dict(record.provenance or {}),
        "derived_from": list(record.derived_from or []),
        "account_id": record.account_id,
        "citation": knowledge_citation(record),
    }


async def search_knowledge_records(
    org_id: str,
    query: str,
    *,
    top_k: int = 5,
    actor_departments: set[str] | None = None,
    is_founder: bool = False,
    granted_record_ids: set[str] | None = None,
) -> list[dict]:
    """Deterministic, permission-filtered search over KnowledgeRecords.

    KnowledgeRecord is source of truth; no vector index required. Scans
    org records, applies can_retrieve fail-closed, scores lexically.
    """
    if not org_id or not (query or "").strip():
        return []
    try:
        async with async_session() as s:
            rows = (
                await s.execute(
                    select(KnowledgeRecord).where(KnowledgeRecord.org_id == org_id)
                )
            ).scalars().all()
        allowed = [
            r
            for r in rows
            if can_retrieve(
                r,
                actor_org_id=org_id,
                actor_departments=actor_departments or set(),
                is_founder=is_founder,
                granted_record_ids=granted_record_ids,
            )[0]
        ]
        scored = []
        for r in allowed:
            score = knowledge_text_score(r, query)
            if score > 0:
                scored.append((score, r))
        scored.sort(key=lambda x: (-x[0], x[1].created_at.timestamp() if x[1].created_at else 0))
        return [_knowledge_hit(r, score) for score, r in scored[: max(1, top_k)]]
    except Exception as e:
        logger.warning("search_knowledge_records failed: %s", e)
        return []


async def hybrid_search(org_id: str, query: str, top_k: int = 5, agent_id: str = ""):
    """Semantic search over stored memories.

    Two stores exist and this used to read neither correctly: it selected
    `memories.embedding` from Postgres, but that column has never existed
    (`Memory` carries content + extra_data only), so every call raised
    UndefinedColumn, was swallowed, and returned []. An agent with a knowledge
    base therefore reported "not found" for everything and hallucinated instead,
    with ok:true and no error anywhere.

    - agent_id given -> the MemoryManager store (pgvector in production, the
      per-agent SQLite file in dev), which is where _store_vector writes.
    - no agent_id -> Postgres rows that carry `extra_data->'embedding'`, which
      is the format etl_url writes. Org-filtered.
    """
    try:
        from aios.core.memory import _embed

        q = _embed(query)

        if agent_id:
            # Same store the MemoryManager writes to, so this works in
            # multi-replica deployments instead of reading a local SQLite file.
            from aios.core.memory import MemoryManager

            return await MemoryManager(agent_id).search_similar(query, top_k=top_k)

        if not org_id:
            return []

        async with async_session() as s:
            try:
                await s.execute(text("SET LOCAL hnsw.ef_search = 100"))
            except Exception:
                pass
            result = await s.execute(
                text(
                    "SELECT id, content, extra_data->>'embedding' AS emb "
                    "FROM memories WHERE org_id=:org "
                    "AND extra_data->>'embedding' IS NOT NULL LIMIT 500"
                ),
                {"org": org_id},
            )
            import json as _json

            scored = []
            for rid, content, emb in result:
                try:
                    stored = _json.loads(emb)
                except (TypeError, ValueError):
                    continue
                dot = sum(a * b for a, b in zip(q, stored))
                scored.append((dot, rid, content))
            scored.sort(key=lambda x: -x[0])
            return [
                {"id": r[1], "content": r[2], "score": round(float(r[0]), 4)}
                for r in scored[:top_k]
            ]
    except Exception as e:
        logger.warning("hybrid_search failed: %s", e)
        return []
