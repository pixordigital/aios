"""Read-only routines API - normalized view over cron/workday/event/fixed sources."""

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from aios.core.routines import get_routine, list_routines
from aios.db.backend import DatabaseBackend, get_db_backend

from .deps import get_current_user, get_org_id

router = APIRouter(prefix="/api/routines", tags=["routines"])


def _routine_out(r) -> dict[str, Any]:
    d = asdict(r)
    for k in ("next_run_at", "last_run_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


@router.get("")
async def list_routines_api(
    source_type: str | None = Query(None),
    mode: str | None = Query(None),
    agent_id: str | None = Query(None),
    enabled: bool | None = Query(None),
    q: str | None = Query(None),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    _user=Depends(get_current_user),
):
    include_disabled = True if enabled is False else enabled is None
    rows = await list_routines(
        db,
        org_id,
        agent_id=agent_id,
        source_type=source_type,
        mode=mode,
        include_disabled=include_disabled,
    )
    if enabled is True:
        rows = [r for r in rows if r.enabled]
    if q:
        ql = q.lower()
        rows = [
            r
            for r in rows
            if ql in r.name.lower()
            or ql in r.routine_id.lower()
            or ql in (r.job_name or "").lower()
        ]
    return [_routine_out(r) for r in rows]


@router.get("/{routine_id:path}")
async def get_routine_api(
    routine_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    _user=Depends(get_current_user),
):
    r = await get_routine(db, org_id, routine_id)
    if not r:
        raise HTTPException(404, "routine not found")
    return _routine_out(r)
