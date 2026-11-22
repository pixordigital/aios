"""OCP API: departments, members, authority, tasks, goals, decisions, events."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from aios.api.deps import get_current_user, get_org_id
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Organization
from aios.governance.ocp import (
    DEFAULT_DEPARTMENTS,
    AuthorityGrant,
    DecisionRecord,
    Department,
    DepartmentMember,
    OrgEvent,
    OrgGoal,
    SharedTask,
    TransitionError,
    authorize,
    decide,
    decision_level,
    execute_decision,
    grant_is_valid,
    missing_decision_fields,
    record_org_event,
    transition_task,
)

router = APIRouter(prefix="/api/ocp", tags=["ocp"])


def _is_founder(user, org) -> bool:
    if user is None or org is None:
        return False
    return (org.extra_data or {}).get("founder_user_id") == user.id or user.role == "owner"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _dept(dept: Department) -> dict:
    return {
        "id": dept.id, "name": dept.name, "slug": dept.slug, "mission": dept.mission,
        "parent_id": dept.parent_id, "is_active": dept.is_active,
    }


def _member(m: DepartmentMember) -> dict:
    return {
        "id": m.id, "department_id": m.department_id, "member_type": m.member_type,
        "user_id": m.user_id, "agent_id": m.agent_id, "title": m.title,
        "is_manager": m.is_manager, "is_active": m.is_active,
    }


def _grant(g: AuthorityGrant) -> dict:
    return {
        "id": g.id, "department_id": g.department_id, "subject_type": g.subject_type,
        "subject_id": g.subject_id, "role": g.role, "actions": g.actions or [],
        "resources": g.resources or {}, "scope": g.scope or {},
        "max_decision_level": g.max_decision_level,
        "valid_from": g.valid_from.isoformat() if g.valid_from else None,
        "valid_until": g.valid_until.isoformat() if g.valid_until else None,
        "revoked_at": g.revoked_at.isoformat() if g.revoked_at else None,
        "granted_by": g.granted_by,
    }


def _task(task: SharedTask) -> dict:
    return {
        "id": task.id, "title": task.title, "objective": task.objective,
        "status": task.status, "priority": task.priority,
        "requesting_department_id": task.requesting_department_id,
        "responsible_department_id": task.responsible_department_id,
        "owner_type": task.owner_type, "owner_id": task.owner_id,
        "deadline": task.deadline.isoformat() if task.deadline else None,
        "expected_deliverable": task.expected_deliverable,
        "blocked_reason": task.blocked_reason,
        "audit_history": task.audit_history or [],
    }


def _goal(g: OrgGoal) -> dict:
    return {
        "id": g.id, "department_id": g.department_id, "title": g.title,
        "description": g.description, "metric_name": g.metric_name,
        "baseline": g.baseline, "target": g.target, "current": g.current,
        "status": g.status, "owner_type": g.owner_type, "owner_id": g.owner_id,
        "due_at": g.due_at.isoformat() if g.due_at else None,
    }


def _event(e: OrgEvent) -> dict:
    return {
        "id": e.id, "event_type": e.event_type, "actor_type": e.actor_type,
        "actor_id": e.actor_id, "entity_type": e.entity_type, "entity_id": e.entity_id,
        "payload": e.payload or {}, "created_at": e.created_at.isoformat() if e.created_at else None,
    }


async def _require_grant_if_policy(
    db: DatabaseBackend,
    *,
    org_id: str,
    subject_type: str,
    subject_id: str,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> None:
    """Deterministic, non-breaking authorize wiring.

    If org has any active grants for subject+action domain, require a matching grant.
    If no grants configured for that subject/action domain, allow (legacy/no-policy).
    """
    rows = (await db.execute(
        select(AuthorityGrant).where(
            AuthorityGrant.org_id == org_id,
            AuthorityGrant.subject_type == subject_type,
            AuthorityGrant.subject_id == subject_id,
        )
    )).scalars().all()
    active = [g for g in rows if grant_is_valid(g, _now())]
    domain = action.split(":", 1)[0]
    relevant = [g for g in active if any(p == "*" or p == action or p == f"{domain}:*" for p in (g.actions or []))]
    if not relevant:
        return
    ok, reason = authorize(active, action, resource_type=resource_type, resource_id=resource_id, now=_now())
    if not ok:
        raise HTTPException(403, reason)


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
    dept = Department(org_id=org_id, name=name, slug=slug, mission=body.get("mission", ""), parent_id=body.get("parent_id"))
    db.add(dept)
    await db.flush()
    record_org_event(db, org_id=org_id, event_type="department.created", actor_type="human", actor_id=user.id,
                     entity_type="department", entity_id=dept.id, payload={"name": name, "slug": slug})
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
        record_org_event(db, org_id=org_id, event_type="department.created", actor_type="human", actor_id=user.id,
                         entity_type="department", entity_id=dept.id, payload={"slug": dept.slug, "bootstrap": True})
    await db.commit()
    return {"created": created, "created_count": len(created), "defaults": len(DEFAULT_DEPARTMENTS)}


# --- Members -----------------------------------------------------------------

@router.get("/departments/{department_id}/members")
async def list_members(department_id: str, db: DatabaseBackend = Depends(get_db_backend), org_id: str = Depends(get_org_id)):
    dept = await db.get(Department, department_id)
    if dept is None or dept.org_id != org_id:
        raise HTTPException(404, "department not found")
    rows = (await db.execute(select(DepartmentMember).where(
        DepartmentMember.org_id == org_id, DepartmentMember.department_id == department_id
    ))).scalars().all()
    return {"items": [_member(m) for m in rows]}


@router.post("/departments/{department_id}/members")
async def create_member(
    department_id: str,
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    dept = await db.get(Department, department_id)
    if dept is None or dept.org_id != org_id:
        raise HTTPException(404, "department not found")
    member_type = (body.get("member_type") or "").strip()
    if member_type not in {"human", "agent"}:
        raise HTTPException(400, "member_type must be human|agent")
    user_id = body.get("user_id")
    agent_id = body.get("agent_id")
    if member_type == "human" and not user_id:
        raise HTTPException(400, "user_id required for human member")
    if member_type == "agent" and not agent_id:
        raise HTTPException(400, "agent_id required for agent member")
    m = DepartmentMember(
        org_id=org_id, department_id=department_id, member_type=member_type,
        user_id=user_id if member_type == "human" else None,
        agent_id=agent_id if member_type == "agent" else None,
        title=body.get("title", ""), is_manager=bool(body.get("is_manager", False)),
    )
    db.add(m)
    await db.flush()
    record_org_event(db, org_id=org_id, event_type="department.member_added", actor_type="human", actor_id=user.id,
                     entity_type="department_member", entity_id=m.id,
                     payload={"department_id": department_id, "member_type": member_type})
    await db.commit()
    await db.refresh(m)
    return _member(m)


@router.delete("/departments/{department_id}/members/{member_id}")
async def delete_member(
    department_id: str,
    member_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    m = await db.get(DepartmentMember, member_id)
    if m is None or m.org_id != org_id or m.department_id != department_id:
        raise HTTPException(404, "member not found")
    await db.delete(m)
    record_org_event(db, org_id=org_id, event_type="department.member_removed", actor_type="human", actor_id=user.id,
                     entity_type="department_member", entity_id=member_id, payload={"department_id": department_id})
    await db.commit()
    return {"ok": True}


# --- Authority grants ---------------------------------------------------------

@router.get("/authority-grants")
async def list_grants(
    subject_type: str = "",
    subject_id: str = "",
    department_id: str = "",
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    q = select(AuthorityGrant).where(AuthorityGrant.org_id == org_id)
    if subject_type:
        q = q.where(AuthorityGrant.subject_type == subject_type)
    if subject_id:
        q = q.where(AuthorityGrant.subject_id == subject_id)
    if department_id:
        q = q.where(AuthorityGrant.department_id == department_id)
    rows = (await db.execute(q.order_by(AuthorityGrant.created_at.desc()))).scalars().all()
    return {"items": [_grant(g) for g in rows]}


@router.post("/authority-grants")
async def create_grant(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    subject_type = (body.get("subject_type") or "").strip()
    subject_id = (body.get("subject_id") or "").strip()
    role = (body.get("role") or "").strip()
    actions = body.get("actions") or []
    if subject_type not in {"human", "agent"} or not subject_id or not role or not actions:
        raise HTTPException(400, "subject_type, subject_id, role, actions required")
    g = AuthorityGrant(
        org_id=org_id, department_id=body.get("department_id"), subject_type=subject_type,
        subject_id=subject_id, role=role, actions=list(actions), resources=body.get("resources") or {},
        scope=body.get("scope") or {}, max_decision_level=int(body.get("max_decision_level", 1)),
        granted_by=user.id,
    )
    db.add(g)
    await db.flush()
    record_org_event(db, org_id=org_id, event_type="authority.granted", actor_type="human", actor_id=user.id,
                     entity_type="authority_grant", entity_id=g.id,
                     payload={"subject_type": subject_type, "subject_id": subject_id, "actions": g.actions})
    await db.commit()
    await db.refresh(g)
    return _grant(g)


@router.post("/authority-grants/{grant_id}/revoke")
async def revoke_grant(
    grant_id: str,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    g = await db.get(AuthorityGrant, grant_id)
    if g is None or g.org_id != org_id:
        raise HTTPException(404, "grant not found")
    if g.revoked_at is None:
        g.revoked_at = _now()
        record_org_event(db, org_id=org_id, event_type="authority.revoked", actor_type="human", actor_id=user.id,
                         entity_type="authority_grant", entity_id=g.id, payload={"subject_id": g.subject_id})
        await db.commit()
    return _grant(g)


# --- Tasks -------------------------------------------------------------------

@router.get("/tasks")
async def list_tasks(
    status: str = "",
    department_id: str = "",
    responsible_department_id: str = "",
    requesting_department_id: str = "",
    owner_type: str = "",
    owner_id: str = "",
    overdue: bool = False,
    my_dept: str = Query("", description="department id for dept view"),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    query = select(SharedTask).where(SharedTask.org_id == org_id)
    if status:
        query = query.where(SharedTask.status == status)
    dept = responsible_department_id or department_id
    if dept:
        query = query.where(SharedTask.responsible_department_id == dept)
    if requesting_department_id:
        query = query.where(SharedTask.requesting_department_id == requesting_department_id)
    if owner_type:
        query = query.where(SharedTask.owner_type == owner_type)
    if owner_id:
        query = query.where(SharedTask.owner_id == owner_id)
    if overdue:
        query = query.where(SharedTask.deadline.is_not(None), SharedTask.deadline < _now(),
                            SharedTask.status.not_in(["completed", "cancelled"]))
    if my_dept:
        query = query.where(
            (SharedTask.responsible_department_id == my_dept) | (SharedTask.requesting_department_id == my_dept)
        )
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
    actor_type = (body.get("actor_type") or "human").strip()
    actor_id = (body.get("actor_id") or user.id).strip()
    if actor_type in {"human", "agent"}:
        await _require_grant_if_policy(db, org_id=org_id, subject_type=actor_type, subject_id=actor_id,
                                       action="task:create", resource_type="department",
                                       resource_id=body.get("responsible_department_id"))
    task = SharedTask(
        org_id=org_id,
        title=title,
        objective=body.get("objective", ""),
        priority=int(body.get("priority", 3)),
        requesting_department_id=body.get("requesting_department_id"),
        responsible_department_id=body.get("responsible_department_id"),
        owner_type=body.get("owner_type"),
        owner_id=body.get("owner_id"),
        expected_deliverable=body.get("expected_deliverable", ""),
    )
    db.add(task)
    await db.flush()
    record_org_event(db, org_id=org_id, event_type="task.created", actor_type="human", actor_id=user.id,
                     entity_type="shared_task", entity_id=task.id, payload={"title": title, "status": task.status})
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
    actor_type = (body.get("actor_type") or "human").strip()
    actor_id = (body.get("actor_id") or user.id).strip()
    if actor_type in {"human", "agent"}:
        await _require_grant_if_policy(db, org_id=org_id, subject_type=actor_type, subject_id=actor_id,
                                       action="task:transition", resource_type="task", resource_id=task.id)
    target = (body.get("target") or "").strip()
    try:
        transition_task(task, target, actor_type, actor_id, body.get("reason", ""))
    except TransitionError as exc:
        raise HTTPException(400, str(exc)) from exc
    record_org_event(db, org_id=org_id, event_type="task.transitioned", actor_type=actor_type, actor_id=actor_id,
                     entity_type="shared_task", entity_id=task.id,
                     payload={"from": task.audit_history[-1]["from"] if task.audit_history else None,
                              "to": task.status, "reason": body.get("reason", "")})
    await db.commit()
    return _task(task)


# --- Goals -------------------------------------------------------------------

@router.get("/goals")
async def list_goals(
    department_id: str = "",
    status: str = "",
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    q = select(OrgGoal).where(OrgGoal.org_id == org_id)
    if department_id:
        q = q.where(OrgGoal.department_id == department_id)
    if status:
        q = q.where(OrgGoal.status == status)
    rows = (await db.execute(q.order_by(OrgGoal.updated_at.desc()))).scalars().all()
    return {"items": [_goal(g) for g in rows]}


@router.post("/goals")
async def create_goal(
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title is required")
    g = OrgGoal(
        org_id=org_id, department_id=body.get("department_id"), title=title,
        description=body.get("description", ""), metric_name=body.get("metric_name", ""),
        baseline=body.get("baseline"), target=body.get("target"), current=body.get("current"),
        status=body.get("status", "active"), owner_type=body.get("owner_type"),
        owner_id=body.get("owner_id"),
    )
    db.add(g)
    await db.flush()
    record_org_event(db, org_id=org_id, event_type="goal.created", actor_type="human", actor_id=user.id,
                     entity_type="org_goal", entity_id=g.id, payload={"title": title})
    await db.commit()
    await db.refresh(g)
    return _goal(g)


@router.patch("/goals/{goal_id}")
async def update_goal(
    goal_id: str,
    body: dict,
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
    user=Depends(get_current_user),
):
    g = await db.get(OrgGoal, goal_id)
    if g is None or g.org_id != org_id:
        raise HTTPException(404, "goal not found")
    for field in ("title", "description", "metric_name", "status", "owner_type", "owner_id", "department_id"):
        if field in body:
            setattr(g, field, body[field])
    for field in ("baseline", "target", "current"):
        if field in body:
            setattr(g, field, body[field])
    record_org_event(db, org_id=org_id, event_type="goal.updated", actor_type="human", actor_id=user.id,
                     entity_type="org_goal", entity_id=g.id, payload={"fields": sorted(body.keys())})
    await db.commit()
    await db.refresh(g)
    return _goal(g)


# --- Decisions ---------------------------------------------------------------

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
        linked_task_ids=list(body.get("linked_task_ids") or []),
    )
    if not record.title:
        raise HTTPException(400, "title is required")
    db.add(record)
    await db.flush()
    record_org_event(db, org_id=org_id, event_type="decision.proposed", actor_type="human", actor_id=user.id,
                     entity_type="decision_record", entity_id=record.id,
                     payload={"level": record.level, "change_type": change_type})
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
    approve = bool(body.get("approve"))
    try:
        decide(record, approve=approve, founder_id=user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    record_org_event(db, org_id=org_id, event_type="decision.decided", actor_type="human", actor_id=user.id,
                     entity_type="decision_record", entity_id=record.id,
                     payload={"approve": approve, "status": record.status, "level": record.level})
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
    actor_type = (body.get("actor_type") or "human").strip()
    actor_id = (body.get("actor_id") or user.id).strip()
    if actor_type in {"human", "agent"}:
        await _require_grant_if_policy(db, org_id=org_id, subject_type=actor_type, subject_id=actor_id,
                                       action="decision:execute", resource_type="decision", resource_id=record.id)
    task_ids = list(body.get("task_ids") or record.linked_task_ids or [])
    tasks = []
    for task_id in task_ids:
        task = await db.get(SharedTask, task_id)
        if task is not None and task.org_id == org_id:
            tasks.append(task)
    try:
        executed = execute_decision(record, tasks, actor_type=actor_type, actor_id=actor_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    record_org_event(db, org_id=org_id, event_type="decision.executed", actor_type=actor_type, actor_id=actor_id,
                     entity_type="decision_record", entity_id=executed.id,
                     payload={"linked_task_ids": executed.linked_task_ids, "status": executed.status})
    await db.commit()
    return {"id": executed.id, "status": executed.status, "linked_task_ids": executed.linked_task_ids}


# --- Events ------------------------------------------------------------------

@router.get("/events")
async def list_events(
    event_type: str = "",
    entity_type: str = "",
    entity_id: str = "",
    limit: int = Query(100, ge=1, le=500),
    db: DatabaseBackend = Depends(get_db_backend),
    org_id: str = Depends(get_org_id),
):
    q = select(OrgEvent).where(OrgEvent.org_id == org_id)
    if event_type:
        q = q.where(OrgEvent.event_type == event_type)
    if entity_type:
        q = q.where(OrgEvent.entity_type == entity_type)
    if entity_id:
        q = q.where(OrgEvent.entity_id == entity_id)
    rows = (await db.execute(q.order_by(OrgEvent.created_at.desc()).limit(limit))).scalars().all()
    return {"items": [_event(e) for e in rows]}
