import logging
import os
import time
from datetime import datetime, timezone

from sqlalchemy import and_, or_, select, text

from aios.db.engine import async_session
from aios.governance.knowledge import (
    KnowledgeRecord,
    can_retrieve,
    knowledge_citation,
    knowledge_text_score,
)

logger = logging.getLogger(__name__)


RAG_STATUS = {"vector": False, "hnsw": False, "knowledge_hnsw": False, "fallback": True}
# Observability guardrail: warn when a filtered KnowledgeRecord scan stays large.
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
                    knowledge_reg = await s.execute(
                        text("SELECT to_regclass('ix_knowledge_vectors_embedding')")
                    )
                    RAG_STATUS["knowledge_hnsw"] = knowledge_reg.scalar() is not None
                else:
                    RAG_STATUS["hnsw"] = False
                    RAG_STATUS["knowledge_hnsw"] = False
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


def _acl_conditions(
    org_id: str,
    actor_departments: set[str],
    is_founder: bool,
    granted_record_ids: set[str],
    now: datetime,
) -> list:
    """Cheap ACL predicates shared by lexical and vector candidate queries."""
    base = [
        KnowledgeRecord.org_id == org_id,
        KnowledgeRecord.deleted_at.is_(None),
        or_(
            KnowledgeRecord.retention_until.is_(None),
            KnowledgeRecord.retention_until >= now,
        ),
    ]
    if is_founder:
        return base
    in_scope = or_(
        KnowledgeRecord.department_id.is_(None),
        KnowledgeRecord.department_id.in_(actor_departments) if actor_departments else False,
    )
    normal = and_(~KnowledgeRecord.classification.in_(("restricted", "confidential")), in_scope)
    confidential = and_(
        KnowledgeRecord.classification == "confidential",
        KnowledgeRecord.id.in_(granted_record_ids) if granted_record_ids else False,
    )
    return [*base, or_(normal, confidential)]


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


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.7f}" for v in vec) + "]"


async def store_knowledge_vectors(
    records: list[KnowledgeRecord], embeddings: list[list[float]]
) -> int:
    """Best-effort pgvector store; never changes governed ACL or ingest result."""
    if not (RAG_STATUS["vector"] and RAG_STATUS["knowledge_hnsw"] and records):
        return 0
    from aios.core.vector_store import use_postgres

    if not use_postgres():
        return 0
    stored = 0
    async with async_session() as s:
        for record, emb in zip(records, embeddings):
            try:
                await s.execute(
                    text(
                        "INSERT INTO knowledge_vectors (record_id, org_id, embedding) "
                        "VALUES (:rid, :org, CAST(:emb AS vector)) "
                        "ON CONFLICT (record_id) DO UPDATE SET embedding = EXCLUDED.embedding"
                    ),
                    {"rid": record.id, "org": record.org_id, "emb": _vec_literal(emb)},
                )
                stored += 1
            except Exception as e:
                logger.warning("knowledge vector store failed record=%s: %s", record.id, e)
        await s.commit()
    return stored


async def _vector_candidates(
    org_id: str, query: str, conditions: list, top_k: int
) -> list[tuple[KnowledgeRecord, float]]:
    """ANN candidates re-filtered through the same ACL as the lexical path."""
    if not (RAG_STATUS["vector"] and RAG_STATUS["knowledge_hnsw"]):
        return []
    try:
        from aios.core.memory import _embed
        from aios.core.vector_store import use_postgres

        if not use_postgres():
            return []
        q = _vec_literal(_embed(query))
        k = max(top_k, 5)
        async with async_session() as s:
            ids = (
                await s.execute(
                    text(
                        "SELECT record_id FROM knowledge_vectors WHERE org_id=:org"
                        " ORDER BY embedding <=> CAST(:emb AS vector) LIMIT :k"
                    ),
                    {"org": org_id, "emb": q, "k": k},
                )
            ).scalars().all()
            if not ids:
                return []
            id_list = [str(i) for i in ids]
            rows = (
                await s.execute(
                    select(KnowledgeRecord).where(KnowledgeRecord.id.in_(id_list), *conditions)
                )
            ).scalars().all()
        # Re-query loses ANN order; restore rank by the original id order.
        rank = {rid: i for i, rid in enumerate(id_list)}
        return [(r, 1.0 - rank[str(r.id)] / k) for r in rows if str(r.id) in rank]
    except Exception as e:
        logger.warning("knowledge vector search failed org=%s: %s", org_id, e)
        return []


async def search_knowledge_records(
    org_id: str,
    query: str,
    *,
    top_k: int = 5,
    actor_departments: set[str] | None = None,
    is_founder: bool = False,
    granted_record_ids: set[str] | None = None,
) -> list[dict]:
    """Permission-filtered search over KnowledgeRecords.

    KnowledgeRecord is source of truth. SQL pushes ACL + query-term predicates,
    can_retrieve re-checks every candidate, lexical score ranks matches; pgvector
    ANN candidates supplement when the migration/index is deployed.
    """
    if not org_id or not (query or "").strip():
        return []
    started = time.perf_counter()
    try:
        # ACL predicates in SQL; can_retrieve still re-checks before scoring.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        acl_conditions = _acl_conditions(
            org_id, actor_departments or set(), is_founder, granted_record_ids or set(), now
        )
        conditions = list(acl_conditions)
        # knowledge_text_score scores a record when ANY query term is present;
        # push that same OR predicate into SQL so non-matching rows are not fetched.
        terms = [t for t in query.lower().split() if t]
        if terms:
            term_predicates = []
            for term in terms:
                pattern = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                term_predicates.append(
                    or_(
                        KnowledgeRecord.title.ilike(pattern, escape="\\"),
                        KnowledgeRecord.content.ilike(pattern, escape="\\"),
                        KnowledgeRecord.search_text.ilike(pattern, escape="\\"),
                    )
                )
            conditions.append(or_(*term_predicates))
        async with async_session() as s:
            rows = (await s.execute(select(KnowledgeRecord).where(*conditions))).scalars().all()
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
        # Vector candidates supplement lexical matches; ACL re-checked per record.
        for record, similarity in await _vector_candidates(org_id, query, acl_conditions, top_k):
            if any(r.id == record.id for _, r in scored):
                continue
            if can_retrieve(
                record,
                actor_org_id=org_id,
                actor_departments=actor_departments or set(),
                is_founder=is_founder,
                granted_record_ids=granted_record_ids,
            )[0]:
                scored.append((similarity, record))
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
):
    """Search knowledge with permission-aware defaults.

    - agent_id given -> agent-scoped MemoryManager store (no cross-agent leakage).
    - no agent_id -> permission-filtered KnowledgeRecord search. Unpermissioned
      legacy Memory scans are not exposed; Memory rows carry no KnowledgeRecord ACL.
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
        return kr
    except Exception as e:
        logger.warning("hybrid_search failed: %s", e)
        return []
