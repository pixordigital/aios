"""OCP API: departments, shared tasks and Founder decision records."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from aios.api.deps import get_current_user, get_org_id
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Organization
from aios.governance.ocp import (
    DEFAULT_DEPARTMENTS,
    DecisionRecord,
    Department,
    SharedTask,
    TransitionError,
    decide,
    decision_level,
    execute_decision,
    missing_decision_fields,
    transition_task,
)

router = APIRouter(prefix="/api/ocp", tags=["ocp"])


def _is_founder(user, org) -> bool:
    if user is None or org is None:
        return False
    return (org.extra_data or {}).get("founder_user_id") == user.id or user.role == "owner"


def _dept(dept: Department) -> dict:
    return {"id": dept.id, "name": dept.name, "slug": dept.slug, "mission": dept.mission,
            "parent_id": dept.parent_id, "is_active": dept.is_active}


def _task(task: SharedTask) -> dict:
    return {
        "id": task.id, "title": task.title, "objective": task.objective,
        "status": task.status, "priority": task.priority,
        "requesting_department_id": task.requesting_department_id,
        "responsible_department_id": task.responsible_department_id,
        "owner_type": task.owner_type, "owner_id": task.owner_id,
        "expected_deliverable": task.expected_deliverable,
        "audit_history": task.audit_history or [],
    }


@router.get("/departments")
async def list_departments(db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    rows = (await db.execute(select(Department).where(Department.org_id == org_id))).scalars().all()
    return {"items": [_dept(d) for d in rows]}


@router.post("/departments")
async def create_department(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    name = (body.get("name") or "").strip()
    slug = (body.get("slug") or "").strip()
    if not name or not slug:
        raise HTTPException(400, "name and slug are required")
    dept = Department(org_id=org_id, name=name, slug=slug, mission=body.get("mission", ""))
    db.add(dept)
    await db.commit()
    await db.refresh(dept)
    return _dept(dept)


@router.post("/departments/bootstrap-defaults")
async def bootstrap_default_departments(
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    """Founder activates lean §6 default departments; idempotent, no agents created."""
    org = await db.get(Organization, org_id)
    if not _is_founder(user, org):
        raise HTTPException(403, "Founder approval required")
    existing = {d.slug for d in (await db.execute(
        select(Department).where(Department.org_id == org_id)
    )).scalars().all()}
    created = []
    for spec in DEFAULT_DEPARTMENTS:
        if spec["slug"] in existing:
            continue
        dept = Department(org_id=org_id, **spec)
        db.add(dept)
        await db.flush()
        created.append(_dept(dept))
    await db.commit()
    return {"created": created, "created_count": len(created), "defaults": len(DEFAULT_DEPARTMENTS)}


@router.get("/tasks")
async def list_tasks(
    status: str = "",
    department_id: str = "",
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    query = select(SharedTask).where(SharedTask.org_id == org_id)
    if status:
        query = query.where(SharedTask.status == status)
    if department_id:
        query = query.where(SharedTask.responsible_department_id == department_id)
    rows = (await db.execute(query.order_by(SharedTask.updated_at.desc()))).scalars().all()
    return {"items": [_task(t) for t in rows]}


@router.post("/tasks")
async def create_task(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title is required")
    task = SharedTask(
        org_id=org_id,
        title=title,
        objective=body.get("objective", ""),
        priority=int(body.get("priority", 3)),
        requesting_department_id=body.get("requesting_department_id"),
        responsible_department_id=body.get("responsible_department_id"),
        expected_deliverable=body.get("expected_deliverable", ""),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return _task(task)


@router.post("/tasks/{task_id}/transition")
async def transition(
    task_id: str,
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    task = await db.get(SharedTask, task_id)
    if task is None or task.org_id != org_id:
        raise HTTPException(404, "task not found")
    try:
        transition_task(
            task,
            (body.get("target") or "").strip(),
            "human",
            user.id,
            body.get("reason", ""),
        )
    except TransitionError as exc:
        raise HTTPException(400, str(exc)) from exc
    except TransitionError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return _task(task)


@router.post("/decisions")
async def propose_decision(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    change_type = (body.get("change_type") or "").strip()
    record = DecisionRecord(
        org_id=org_id,
        level=decision_level(change_type),
        change_type=change_type,
        title=(body.get("title") or "").strip(),
        justification=body.get("justification") or {},
        evidence=body.get("evidence") or {},
        requested_by_type="human",
        requested_by_id=user.id,
    )
    if not record.title:
        raise HTTPException(400, "title is required")
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {
        "id": record.id,
        "level": record.level,
        "status": record.status,
        "missing_fields": missing_decision_fields(record.justification),
    }


@router.post("/decisions/{decision_id}/decide")
async def decide_record(
    decision_id: str,
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    record = await db.get(DecisionRecord, decision_id)
    if record is None or record.org_id != org_id:
        raise HTTPException(404, "decision not found")
    org = await db.get(Organization, org_id)
    if not _is_founder(user, org):
        raise HTTPException(403, "Founder approval required")
    try:
        decide(record, approve=bool(body.get("approve")), founder_id=user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return {"id": record.id, "status": record.status, "decided_by": record.decided_by}


@router.post("/decisions/{decision_id}/execute")
async def execute_decision_route(
    decision_id: str,
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    record = await db.get(DecisionRecord, decision_id)
    if record is None or record.org_id != org_id:
        raise HTTPException(404, "decision not found")
    task_ids = list(body.get("task_ids") or record.linked_task_ids or [])
    tasks = []
    for task_id in task_ids:
        task = await db.get(SharedTask, task_id)
        if task is not None and task.org_id == org_id:
            tasks.append(task)
    try:
        executed = execute_decision(
            record, tasks, actor_type="human", actor_id=user.id
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    return {
        "id": executed.id,
        "status": executed.status,
        "linked_task_ids": executed.linked_task_ids,
    }
