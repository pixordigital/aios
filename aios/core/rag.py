import logging

from sqlalchemy import text

from aios.db.engine import async_session

logger = logging.getLogger(__name__)


async def ensure_vector_extension():
    try:
        async with async_session() as s:
            await s.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await s.commit()
            try:
                await s.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_memories_embedding_hnsw ON memories USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)"
                    )
                )
                await s.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_memories_org_id ON memories (org_id)"
                    )
                )
                await s.commit()
            except Exception:
                pass
    except Exception:
        logger.debug("vector extension not available")


async def hybrid_search(org_id: str, query: str, top_k: int = 5):
    try:
        from aios.core.memory import _embed

        q = _embed(query)
        q_str = "[" + ",".join(f"{x:.6f}" for x in q) + "]"
        async with async_session() as s:
            rows = await s.execute(
                text(
                    "SELECT id, content, 1 - (embedding <=> CAST(:q AS vector)) as score "
                    "FROM memories WHERE org_id=:org ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
                ),
                {"q": q_str, "org": org_id, "k": top_k},
            )
            return [{"id": r[0], "content": r[1], "score": float(r[2])} for r in rows]
    except Exception as e:
        logger.debug("hybrid_search fallback: %s", e)
        return []
