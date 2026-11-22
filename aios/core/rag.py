import json as _json
import logging
import os
import time

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
# Observability guardrail: full-org KnowledgeRecord scan can be expensive.
# No index/migration here; warn when scan size crosses threshold.
RAG_SCAN_WARN_THRESHOLD = max(1, int(os.getenv("AIOS_RAG_SCAN_WARN_THRESHOLD", "5000")))

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
    started = time.perf_counter()
    try:
        async with async_session() as s:
            rows = (
                await s.execute(
                    select(KnowledgeRecord).where(KnowledgeRecord.org_id == org_id)
                )
            ).scalars().all()
        scanned = len(rows)
        elapsed_ms = (time.perf_counter() - started) * 1000
        if scanned > RAG_SCAN_WARN_THRESHOLD:
            logger.warning(
                "search_knowledge_records full-org scan exceeded threshold org=%s scanned=%d threshold=%d ms=%.2f",
                org_id,
                scanned,
                RAG_SCAN_WARN_THRESHOLD,
                elapsed_ms,
            )
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
        hits = [_knowledge_hit(r, score) for score, r in scored[: max(1, top_k)]]
        logger.debug(
            "search_knowledge_records org=%s scanned=%d allowed=%d matched=%d returned=%d ms=%.2f",
            org_id,
            scanned,
            len(allowed),
            len(scored),
            len(hits),
            (time.perf_counter() - started) * 1000,
        )
        return hits
    except Exception as e:
        logger.warning(
            "search_knowledge_records failed org=%s ms=%.2f: %s",
            org_id,
            (time.perf_counter() - started) * 1000,
            e,
        )
        return []


async def hybrid_search(
    org_id: str,
    query: str,
    top_k: int = 5,
    agent_id: str = "",
    *,
    actor_departments: set[str] | None = None,
    is_founder: bool = False,
    granted_record_ids: set[str] | None = None,
    include_legacy_memory: bool = False,
    allow_legacy_unpermissioned: bool = False,
    internal_caller: bool = False,
):
    """Search knowledge with permission-aware defaults.

    - agent_id given -> legacy agent MemoryManager store (agent-scoped memory).
      Not a KnowledgeRecord; kept for backward compat, no cross-agent leakage.
    - no agent_id -> permission-filtered KnowledgeRecord search (source of truth).
      Fails closed on classification/dept/grants. Legacy raw Memory scan is
      disabled by default because Memory rows have no KnowledgeRecord ACL.
      Escape hatch requires include_legacy_memory=True AND
      allow_legacy_unpermissioned=True AND internal_caller=True; all three must
      be set explicitly by trusted internal code. Never expose this path to
      user/agent-controlled tool args.
    """
    try:
        if agent_id:
            # Agent-scoped memory store; same boundary as MemoryManager.
            from aios.core.memory import MemoryManager

            return await MemoryManager(agent_id).search_similar(query, top_k=top_k)

        if not org_id:
            return []

        # Governed KnowledgeRecords are source of truth.
        kr = await search_knowledge_records(
            org_id,
            query,
            top_k=top_k,
            actor_departments=actor_departments or set(),
            is_founder=is_founder,
            granted_record_ids=granted_record_ids,
        )
        legacy_allowed = (
            include_legacy_memory
            and allow_legacy_unpermissioned
            and internal_caller
        )
        if kr or not legacy_allowed:
            if include_legacy_memory and not legacy_allowed:
                logger.warning(
                    "hybrid_search blocked legacy Memory path for org=%s: "
                    "requires include_legacy_memory, allow_legacy_unpermissioned, "
                    "and internal_caller all true",
                    org_id,
                )
            return kr

        # Explicit internal-only legacy Memory scan (not KnowledgeRecord-governed).
        logger.warning(
            "hybrid_search using legacy Memory path for org=%s; "
            "not KnowledgeRecord-permissioned; internal_caller=%s",
            org_id,
            internal_caller,
        )
        from aios.core.memory import _embed

        q = _embed(query)
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
                {
                    "id": r[1],
                    "content": r[2],
                    "score": round(float(r[0]), 4),
                    "source": "legacy_memory",
                    "legacy_unpermissioned": True,
                }
                for r in scored[:top_k]
            ]
    except Exception as e:
        logger.warning("hybrid_search failed: %s", e)
        return []
