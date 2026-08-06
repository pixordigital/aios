"""Library API — unified search across artifacts, skills, messages."""

from fastapi import APIRouter, Depends

from aios.api.deps import get_current_user, get_org_id
from aios.core.library import library
from aios.db.models import User

router = APIRouter(prefix="/api/library", tags=["library"])


@router.get("/search")
async def search_library(
    q: str = "",
    type: str = "",
    user: User = Depends(get_current_user),
    org_id: str = Depends(get_org_id),
):
    results = await library.search(q, org_id, item_type=type)
    return {"results": results, "count": len(results)}


@router.get("/recent")
async def recent_items(
    user: User = Depends(get_current_user),
    org_id: str = Depends(get_org_id),
):
    results = await library.recent(org_id)
    return {"results": results}


@router.get("/stats")
async def library_stats(
    user: User = Depends(get_current_user),
    org_id: str = Depends(get_org_id),
):
    return await library.stats(org_id)
