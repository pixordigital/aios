"""SPARC workflow API — 6-phase methodology (spec→refactor)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from aios.api.deps import get_current_user, get_org_id
from aios.core.sparc import sparc_engine, PHASES
from aios.db.models import User

router = APIRouter(prefix="/api/sparc", tags=["sparc"])


class SparcCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    agent_id: str | None = None
    context: dict = Field(default_factory=dict)
    max_iterations: int = Field(default=1, ge=1, le=5)


@router.post("")
async def create_sparc(
    body: SparcCreate,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    wf = await sparc_engine.create(
        org_id=org_id, name=body.name, description=body.description,
        agent_id=body.agent_id, context=body.context, max_iterations=body.max_iterations,
    )
    return wf


@router.get("")
async def list_sparc(
    limit: int = Query(20, ge=1, le=100),
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    rows = await sparc_engine.list(org_id=org_id, limit=limit)
    return {"items": rows}


@router.get("/{workflow_id}")
async def get_sparc(
    workflow_id: str,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    wf = await sparc_engine.get(workflow_id)
    if not wf or wf.org_id != org_id:
        raise HTTPException(404, "sparc workflow not found")
    return wf


class PhaseAdvanceBody(BaseModel):
    output: dict = Field(default_factory=dict)
    agent_id: str | None = None


@router.post("/{workflow_id}/advance")
async def advance_phase(
    workflow_id: str, body: PhaseAdvanceBody,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    wf = await sparc_engine.get(workflow_id)
    if not wf or wf.org_id != org_id:
        raise HTTPException(404, "sparc workflow not found")
    if wf.status != "active":
        raise HTTPException(400, f"workflow status is {wf.status}")
    wf2 = await sparc_engine.advance(
        workflow_id=workflow_id, phase_output=body.output,
        agent_id=body.agent_id or wf.agent_id,
    )
    return wf2


@router.post("/{workflow_id}/fail")
async def fail_phase(
    workflow_id: str, error: str = "",
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    wf = await sparc_engine.fail_phase(workflow_id=workflow_id, error=error)
    if not wf:
        raise HTTPException(404, "sparc workflow not found")
    return wf


@router.get("/{workflow_id}/logs")
async def sparc_logs(
    workflow_id: str,
    limit: int = Query(50, ge=1, le=200),
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    wf = await sparc_engine.get(workflow_id)
    if not wf or wf.org_id != org_id:
        raise HTTPException(404, "sparc workflow not found")
    logs = await sparc_engine.logs(workflow_id, limit=limit)
    return {"items": logs}


@router.get("/{workflow_id}/instruction")
async def phase_instruction(
    workflow_id: str,
    org_id: str = Depends(get_org_id),
    user: User = Depends(get_current_user),
):
    wf = await sparc_engine.get(workflow_id)
    if not wf or wf.org_id != org_id:
        raise HTTPException(404, "sparc workflow not found")
    return {
        "phase": wf.current_phase,
        "status": wf.phase_status,
        "instruction": sparc_engine.phase_instruction(wf.current_phase, wf),
        "phases": PHASES,
    }
