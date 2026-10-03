import logging

from sqlalchemy import text

from aios.db.engine import async_session

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
                # `memories` has no `embedding` column (embeddings live in the
                # per-agent SQLite store, or in extra_data->'embedding'), so the
                # HNSW index could never be created and `hnsw` stayed False
                # forever while claiming readiness. Index what exists.
                await s.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_memories_org_id ON memories (org_id)"
                    )
                )
                await s.commit()
                RAG_STATUS["hnsw"] = False
                RAG_STATUS["fallback"] = False
                logger.info("vector extension ready; embeddings stored per-agent in SQLite")
            except Exception as e:
                logger.warning("pgvector HNSW index failed, fallback sqlite: %s", e)
                RAG_STATUS["fallback"] = True
    except Exception as e:
        logger.warning("vector extension not available, RAG fallback sqlite: %s", e)
        RAG_STATUS["vector"] = False
        RAG_STATUS["fallback"] = True


async def hybrid_search(org_id: str, query: str, top_k: int = 5, agent_id: str = ""):
    """Semantic search over stored memories.

    Two stores exist and this used to read neither correctly: it selected
    `memories.embedding` from Postgres, but that column has never existed
    (`Memory` carries content + extra_data only), so every call raised
    UndefinedColumn, was swallowed, and returned []. An agent with a knowledge
    base therefore reported "not found" for everything and hallucinated instead,
    with ok:true and no error anywhere.

    - agent_id given -> the per-agent SQLite vector store, which is where
      MemoryManager._store_vector actually writes the embeddings.
    - no agent_id -> Postgres rows that carry `extra_data->'embedding'`, which
      is the format etl_url writes. Org-filtered.
    """
    try:
        from aios.core.memory import _embed

        q = _embed(query)

        if agent_id:
            from aios.core.memory import _vec_db

            conn = _vec_db(agent_id)
            rows = conn.execute(
                "SELECT id, content, embedding FROM memories ORDER BY rowid DESC LIMIT 500"
            ).fetchall()
            import json as _json

            scored = []
            for rid, content, emb in rows:
                if not emb:
                    continue
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

        if not org_id:
            return []

        async with async_session() as s:
            try:
                await s.execute(text("SET LOCAL hnsw.ef_search = 100"))
            except Exception:
                pass
            rows = await s.execute(
                text(
                    "SELECT id, content, extra_data->>'embedding' AS emb "
                    "FROM memories WHERE org_id=:org "
                    "AND extra_data->>'embedding' IS NOT NULL LIMIT 500"
                ),
                {"org": org_id},
            )
            import json as _json

            scored = []
            for rid, content, emb in rows:
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
