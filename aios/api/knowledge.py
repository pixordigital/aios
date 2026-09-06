from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Memory
from .deps import get_current_user, get_org_id

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

@router.get("/search")
async def search(q: str = Query(...), top_k: int = 5, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    from aios.core.rag import hybrid_search
    results = await hybrid_search(org_id, q, top_k)
    if not results:
        rows = (await db.execute(select(Memory).where(Memory.org_id==org_id).order_by(Memory.created_at.desc()).limit(top_k))).scalars().all()
        # fallback keyword
        filtered = [r for r in rows if q.lower() in (r.content or "").lower()]
        results = [{"id": r.id, "content": r.content[:600], "score": 0.5} for r in (filtered or rows)[:top_k]]
    return {"query": q, "results": results}

@router.get("/memories")
async def list_memories(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), limit: int = 50):
    rows = (await db.execute(select(Memory).where(Memory.org_id==org_id).order_by(Memory.created_at.desc()).limit(limit))).scalars().all()
    return [{"id": r.id, "content": r.content[:600], "type": r.type, "agent_id": r.agent_id, "created_at": str(r.created_at)} for r in rows]
