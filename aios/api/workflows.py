from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.models import Workflow, WorkflowNode, WorkflowRun, Agent, Conversation
from aios.schemas import BaseModel
from .deps import get_current_user, get_org_id

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

def _require_role(user, allowed: list[str]):
    if user.role not in allowed and user.role != "superadmin":
        from fastapi import HTTPException as _HE
        raise _HE(403, f"role {user.role} not allowed, need {allowed}")

class WorkflowCreate(BaseModel):
    name: str
    description: str = ""
    timeout_seconds: int = 120
    entry_node_id: str | None = None

class WorkflowOut(BaseModel):
    id: str
    name: str
    description: str
    status: str
    timeout_seconds: int
    entry_node_id: str | None
    org_id: str
    created_at: str | None = None

class NodeCreate(BaseModel):
    label: str = ""
    agent_id: str | None = None
    tool_name: str | None = None
    tool_args: dict = {}
    depends_on: list[str] = []
    condition: str | None = None
    output_key: str = "result"
    timeout_seconds: int = 60
    position: dict = {}

@router.post("", response_model=WorkflowOut)
async def create_workflow(body: WorkflowCreate, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    _require_role(user, ["admin", "org_admin"])
    # per-agent quota check
    from aios.core.agent_health import health_tracker as _ht
    from aios.config import PLANS
    from aios.db.models import Organization
    org = await db.get(Organization, org_id)
    plan = (org.extra_data.get("plan", "free") if org else "free")
    if plan not in ("unlimited", "enterprise") and plan != "pro":
        existing = (await db.execute(select(Workflow).where(Workflow.org_id == org_id))).scalars().all()
        if len(existing) >= 20:
            raise HTTPException(403, detail="Workflow quota exceeded for plan")
    wf = Workflow(org_id=org_id, name=body.name, description=body.description, timeout_seconds=body.timeout_seconds, entry_node_id=body.entry_node_id)
    db.add(wf)
    await db.commit()
    await db.refresh(wf)
    return wf

@router.get("", response_model=list[WorkflowOut])
async def list_workflows(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    res = await db.execute(select(Workflow).where(Workflow.org_id == org_id).order_by(Workflow.created_at.desc()).limit(limit).offset(offset))
    return res.scalars().all()

@router.get("/{wf_id}")
async def get_workflow(wf_id: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    wf = await db.get(Workflow, wf_id, options=[selectinload(Workflow.nodes)])
    if not wf or wf.org_id != org_id:
        raise HTTPException(404)
    return {"id": wf.id, "name": wf.name, "description": wf.description, "status": wf.status, "timeout_seconds": wf.timeout_seconds, "entry_node_id": wf.entry_node_id, "org_id": wf.org_id, "nodes": [{"id": n.id, "label": n.label, "agent_id": n.agent_id, "tool_name": n.tool_name, "tool_args": n.tool_args, "depends_on": n.depends_on, "condition": n.condition, "output_key": n.output_key, "position": n.position} for n in wf.nodes]}

@router.put("/{wf_id}", response_model=WorkflowOut)
async def update_workflow(wf_id: str, body: WorkflowCreate, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    wf = await db.get(Workflow, wf_id)
    if not wf or wf.org_id != org_id:
        raise HTTPException(404)
    wf.name = body.name
    wf.description = body.description
    wf.timeout_seconds = body.timeout_seconds
    if body.entry_node_id:
        wf.entry_node_id = body.entry_node_id
    await db.commit()
    await db.refresh(wf)
    return wf

@router.delete("/{wf_id}")
async def delete_workflow(wf_id: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    wf = await db.get(Workflow, wf_id)
    if not wf or wf.org_id != org_id:
        raise HTTPException(404)
    await db.delete(wf)
    await db.commit()
    return {"ok": True}

@router.post("/{wf_id}/nodes")
async def add_node(wf_id: str, body: NodeCreate, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    wf = await db.get(Workflow, wf_id)
    if not wf or wf.org_id != org_id:
        raise HTTPException(404)
    _require_role(user, ["admin", "org_admin"])
    if body.agent_id:
        ag = await db.get(Agent, body.agent_id)
        if not ag or ag.org_id != org_id:
            raise HTTPException(400, detail="agent not found in org")
        from aios.core.agent_health import health_tracker
        if not health_tracker.is_available(ag.id):
            raise HTTPException(409, detail=f"agent {ag.name} is stopped (circuit breaker open)")
    # cycle check
    existing_nodes = (await db.execute(select(WorkflowNode).where(WorkflowNode.workflow_id == wf_id))).scalars().all()
    all_ids = {n.id for n in existing_nodes} | {"new"}
    for dep in (body.depends_on or []):
        if dep not in {n.id for n in existing_nodes}:
            raise HTTPException(400, detail=f"depends_on {dep} not found")
    node = WorkflowNode(workflow_id=wf_id, label=body.label, agent_id=body.agent_id, tool_name=body.tool_name, tool_args=body.tool_args, depends_on=body.depends_on, condition=body.condition, output_key=body.output_key, timeout_seconds=body.timeout_seconds, position=body.position)
    db.add(node)
    await db.flush()
    # dfs cycle detect
    nodes = list(existing_nodes) + [node]
    vis, stack = set(), set()
    def dfs(nid):
        if nid in stack:
            return True
        if nid in vis:
            return False
        vis.add(nid); stack.add(nid)
        n = next((x for x in nodes if x.id == nid), None)
        if n:
            for d in (n.depends_on or []):
                if dfs(d):
                    return True
        stack.remove(nid)
        return False
    for n in nodes:
        if dfs(n.id):
            await db.rollback()
            raise HTTPException(400, detail="cycle detected")
    await db.commit()
    await db.refresh(node)
    return {"id": node.id, "label": node.label, "agent_id": node.agent_id, "tool_name": node.tool_name}

@router.delete("/{wf_id}/nodes/{node_id}")
async def delete_node(wf_id: str, node_id: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    node = await db.get(WorkflowNode, node_id)
    if not node or node.workflow_id != wf_id:
        raise HTTPException(404)
    wf = await db.get(Workflow, wf_id)
    if wf.org_id != org_id:
        raise HTTPException(404)
    await db.delete(node)
    await db.commit()
    return {"ok": True}

@router.post("/{wf_id}/run")
async def run_workflow(wf_id: str, body: dict = {}, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    wf = await db.get(Workflow, wf_id, options=[selectinload(Workflow.nodes)])
    if not wf or wf.org_id != org_id:
        raise HTTPException(404)
    if not wf.nodes:
        raise HTTPException(400, detail="workflow has no nodes")
    initial_input = body.get("input") or body.get("message") or ""
    conversation_id = body.get("conversation_id")
    from aios.core.workflow import WorkflowDef, WorkflowNode as WNode, WorkflowEngine
    wdef = WorkflowDef(id=wf.id, name=wf.name, timeout=wf.timeout_seconds, entry_node=wf.entry_node_id)
    for n in wf.nodes:
        wdef.nodes[n.id] = WNode(id=n.id, agent_id=n.agent_id, tool_name=n.tool_name, tool_args=n.tool_args or {}, depends_on=n.depends_on or [], condition=n.condition, output_key=n.output_key, timeout=n.timeout_seconds)
    run = WorkflowRun(workflow_id=wf.id, org_id=org_id, conversation_id=conversation_id, status="running", inputs={"input": initial_input})
    db.add(run)
    await db.commit()
    await db.refresh(run)
    engine = WorkflowEngine()
    try:
        result = await engine.run(wdef, conversation_id or run.id, initial_input)
        run.status = "done" if result.ok() else "failed"
        run.outputs = result.outputs
        run.node_status = result.node_status
        if result.errors:
            run.error = str(result.errors)
        await db.commit()
        return {"run_id": run.id, "status": run.status, "outputs": run.outputs, "node_status": run.node_status, "errors": result.errors}
    except Exception as e:
        run.status = "failed"
        run.error = str(e)
        await db.commit()
        raise HTTPException(500, detail=str(e))

@router.get("/{wf_id}/runs")
async def list_runs(wf_id: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), limit: int = Query(20, ge=1, le=100)):
    res = await db.execute(select(WorkflowRun).where(WorkflowRun.workflow_id == wf_id, WorkflowRun.org_id == org_id).order_by(WorkflowRun.created_at.desc()).limit(limit))
    return res.scalars().all()


@router.post("/{wf_id}/eval")
async def eval_workflow_run(wf_id: str, body: dict, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    from aios.core.rubric import rubric_manager
    from aios.core.providers import get_provider
    wf = await db.get(Workflow, wf_id)
    if not wf or wf.org_id != org_id:
        raise HTTPException(404)
    run_id = body.get("run_id")
    rubric_id = body.get("rubric_id")
    if not run_id or not rubric_id:
        raise HTTPException(400, detail="run_id and rubric_id required")
    run = await db.get(WorkflowRun, run_id)
    if not run or run.workflow_id != wf_id:
        raise HTTPException(404, detail="run not found")
    output = json.dumps(run.outputs) if run.outputs else run.error or ""
    llm = get_provider("openai/gpt-4o-mini")
    scored = await rubric_manager.score_response(rubric_id, output[:4000], llm_provider=llm)
    run.extra_data = {**(run.extra_data or {}), "eval": scored}
    await db.commit()
    return scored


@router.post("/{wf_id}/replay/{run_id}")
async def replay_run(wf_id: str, run_id: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id), user=Depends(get_current_user)):
    orig = await db.get(WorkflowRun, run_id)
    if not orig or orig.workflow_id != wf_id or orig.org_id != org_id:
        raise HTTPException(404)
    new_run = WorkflowRun(workflow_id=wf_id, org_id=org_id, conversation_id=orig.conversation_id, status="pending", inputs=dict(orig.inputs or {}))
    db.add(new_run)
    await db.commit()
    await db.refresh(new_run)
    try:
        from aios.tasks.queue import enqueue_job
        await enqueue_job("aios.tasks.jobs.workflow_run_job", {"workflow_id": wf_id, "run_id": new_run.id})
    except Exception:
        # fallback sync
        from aios.core.workflow import WorkflowDef, WorkflowNode as WNode, WorkflowEngine
        from sqlalchemy.orm import selectinload
        wf = await db.get(Workflow, wf_id, options=[selectinload(Workflow.nodes)])
        wdef = WorkflowDef(id=wf.id, name=wf.name, timeout=wf.timeout_seconds, entry_node=wf.entry_node_id)
        for n in wf.nodes:
            wdef.nodes[n.id] = WNode(id=n.id, agent_id=n.agent_id, tool_name=n.tool_name, tool_args=n.tool_args or {}, depends_on=n.depends_on or [], condition=n.condition, output_key=n.output_key, timeout=n.timeout_seconds)
        eng = WorkflowEngine()
        res = await eng.run(wdef, new_run.conversation_id or new_run.id, (new_run.inputs or {}).get("input", ""))
        new_run.status = "done" if res.ok() else "failed"
        new_run.outputs = res.outputs
        new_run.node_status = res.node_status
        await db.commit()
    return {"new_run_id": new_run.id, "status": new_run.status}
