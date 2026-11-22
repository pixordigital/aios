"""Organizational Control Plane primitives.

One shared registry for departments, membership, delegated authority, tasks,
goals and decisions. Deterministic code owns state transitions and authority
checks; LLMs may propose but never approve (see docs/OCP.md).

Kept in a separate module so the models register through `aios.db.models`
without bloating it. `aios.db.models` imports this module for its side effect.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aios.db.engine import Base


def _uuid() -> str:
    import uuid

    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


# --- Organizational structure ------------------------------------------------


class Department(Base, TimestampMixin):
    """Enduring responsibility area, not a person or an agent."""

    __tablename__ = "departments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100), index=True)
    mission: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("org_id", "slug", name="uq_department_org_slug"),)


class DepartmentMember(Base, TimestampMixin):
    """Unified human/agent membership. Humans and agents stay distinct subjects."""

    __tablename__ = "department_members"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    member_type: Mapped[str] = mapped_column(String(10))  # human | agent
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(120), default="")
    is_manager: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    __table_args__ = (
        UniqueConstraint("department_id", "user_id", name="uq_dept_member_user"),
        UniqueConstraint("department_id", "agent_id", name="uq_dept_member_agent"),
        Index("ix_dept_member_org_type", "org_id", "member_type"),
    )


class AuthorityGrant(Base, TimestampMixin):
    """Delegated authority with explicit action/resource/scope and expiry.

    `actions` are `resource:verb` strings, e.g. `task:transition`, `budget:read`,
    `decision:propose`. Wildcards (`*`, `task:*`) are allowed but still bounded by
    the grant's validity window and revocation.
    """

    __tablename__ = "authority_grants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    subject_type: Mapped[str] = mapped_column(String(10))  # human | agent
    subject_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(120))
    actions: Mapped[list] = mapped_column(JSON, default=list)
    resources: Mapped[dict] = mapped_column(JSON, default=dict)  # {type: [ids]}, empty = all in scope
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    max_decision_level: Mapped[int] = mapped_column(default=1)
    valid_from: Mapped[datetime | None] = mapped_column(nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    granted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    __table_args__ = (Index("ix_authority_subject", "org_id", "subject_type", "subject_id"),)


# --- Shared task registry -----------------------------------------------------


TASK_STATES = (
    "new",
    "triage",
    "ready",
    "in_progress",
    "blocked",
    "review",
    "completed",
    "cancelled",
)

# Requested -> Triage -> Ready -> In Progress -> Blocked -> Review -> Completed.
TASK_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "new": ("triage", "cancelled"),
    "triage": ("ready", "blocked", "cancelled"),
    "ready": ("in_progress", "blocked", "cancelled"),
    "in_progress": ("review", "blocked", "cancelled"),
    "blocked": ("triage", "ready", "in_progress", "cancelled"),
    "review": ("completed", "in_progress", "cancelled"),
    "completed": (),
    "cancelled": (),
}


class SharedTask(Base, TimestampMixin):
    """One registry, team-specific views. Not a per-team duplicate task table."""

    __tablename__ = "shared_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    objective: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    priority: Mapped[int] = mapped_column(default=3)  # 1 highest .. 5 lowest
    requesting_department_id: Mapped[str | None] = mapped_column(
        ForeignKey("departments.id"), nullable=True
    )
    responsible_department_id: Mapped[str | None] = mapped_column(
        ForeignKey("departments.id"), index=True, nullable=True
    )
    owner_type: Mapped[str | None] = mapped_column(String(10), nullable=True)  # human | agent
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(nullable=True)
    dependencies: Mapped[list] = mapped_column(JSON, default=list)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    expected_deliverable: Mapped[str] = mapped_column(Text, default="")
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)
    budget_id: Mapped[str | None] = mapped_column(ForeignKey("budgets.id"), nullable=True)
    blocked_reason: Mapped[str] = mapped_column(Text, default="")
    audit_history: Mapped[list] = mapped_column(JSON, default=list)
    __table_args__ = (Index("ix_shared_task_dept_status", "org_id", "responsible_department_id", "status"),)


class OrgGoal(Base, TimestampMixin):
    """Department or organizational goal with a measurable target."""

    __tablename__ = "org_goals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    metric_name: Mapped[str] = mapped_column(String(120), default="")
    baseline: Mapped[float | None] = mapped_column(nullable=True)
    target: Mapped[float | None] = mapped_column(nullable=True)
    current: Mapped[float | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    owner_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(nullable=True)


# --- Decisions and organizational events -------------------------------------


DECISION_LEVELS = {
    1: "routine",
    2: "material",
    3: "strategic_high_risk",
}

# Deterministic mapping. Unknown change types default to level 2 (material):
# fail closed toward review rather than silently treating it as routine.
DECISION_LEVEL_BY_CHANGE = {
    "execute_approved_process": 1,
    "new_skill": 2,
    "new_workflow": 2,
    "new_integration": 2,
    "new_tool": 2,
    "new_provider_model": 2,
    "budget_change": 2,
    "process_change": 2,
    "model_default_change": 2,
    "quality_threshold_change": 2,
    "org_restructure": 3,
    "business_model_change": 3,
    "sensitive_data_processing": 3,
    "high_impact_automation": 3,
    "major_infrastructure_change": 3,
}

# Founder Decision & Justification Protocol, in order.
DECISION_PROTOCOL_FIELDS = (
    "proposal",
    "necessity",
    "business_value",
    "lawful_compliance",
    "process_improvement",
    "expected_gains",
    "costs",
    "risks",
    "alternatives",
    "implementation",
    "success_criteria",
    "recommendation",
)

DECISION_STATUSES = ("proposed", "under_review", "approved", "rejected", "executing", "completed", "cancelled")

# Pragmatic bridge only — NOT PendingAction/ApprovalManager unification.
APPROVAL_BRIDGE_REF_TYPES = ("pending_action", "approval_manager", "external_ticket", "manual")
APPROVAL_BRIDGE_STATUSES = ("pending", "approved", "rejected", "cancelled", "unknown")


class DecisionRecord(Base, TimestampMixin):
    """One shared decision capability. No parallel approval systems."""

    __tablename__ = "decision_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    level: Mapped[int] = mapped_column(default=2)
    change_type: Mapped[str] = mapped_column(String(80), default="")
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="proposed", index=True)
    justification: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    requested_by_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    requested_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    linked_task_ids: Mapped[list] = mapped_column(JSON, default=list)
    confidentiality: Mapped[str] = mapped_column(String(30), default="internal")


class OrgEvent(Base, TimestampMixin):
    """Append-only organizational signal feed (task/decision/goal changes)."""

    __tablename__ = "org_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    actor_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(50), default="")
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


# --- Deterministic rules ------------------------------------------------------


class TransitionError(ValueError):
    """Illegal task state transition."""


def record_org_event(
    db,
    *,
    org_id: str,
    event_type: str,
    actor_type: str | None = None,
    actor_id: str | None = None,
    entity_type: str = "",
    entity_id: str | None = None,
    payload: dict | None = None,
) -> OrgEvent:
    """Append-only OrgEvent emitter. Caller owns commit/flush."""
    event = OrgEvent(
        org_id=org_id,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload or {},
    )
    db.add(event)
    return event


def can_transition(current: str, target: str) -> bool:
    return target in TASK_TRANSITIONS.get(current, ())


def transition_task(task: SharedTask, target: str, actor_type: str, actor_id: str, reason: str = "") -> SharedTask:
    """Apply a state change or raise. History is append-only JSON."""
    if not can_transition(task.status, target):
        raise TransitionError(f"illegal transition {task.status} -> {target}")
    history = list(task.audit_history or [])
    history.append(
        {
            "at": _now().isoformat(),
            "from": task.status,
            "to": target,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "reason": reason,
        }
    )
    task.status = target
    task.audit_history = history
    if target == "blocked":
        task.blocked_reason = reason
    return task


def action_matches(pattern: str, action: str) -> bool:
    if pattern == "*" or pattern == action:
        return True
    if pattern.endswith(":*"):
        return action.split(":", 1)[0] == pattern[:-2]
    return False


def grant_is_valid(grant: AuthorityGrant, now: datetime | None = None) -> bool:
    now = now or _now()
    if grant.revoked_at is not None:
        return False
    if grant.valid_from is not None and now < grant.valid_from:
        return False
    if grant.valid_until is not None and now > grant.valid_until:
        return False
    return True


def ocp_strict_default_deny(org_extra_data: dict | None) -> bool:
    """Optional OCP strict mode: deny when no relevant grant is configured.

    Default off for compatibility. Flag lives in org extra_data to avoid schema
    changes: `{"ocp": {"strict_default_deny": true}}`.
    """
    return bool(ocp_policy(org_extra_data).get("strict_default_deny"))


def ocp_policy(org_extra_data: dict | None) -> dict:
    """Normalized OCP policy view over org.extra_data (no schema change)."""
    extra = org_extra_data or {}
    ocp_cfg = extra.get("ocp") if isinstance(extra, dict) else None
    if not isinstance(ocp_cfg, dict):
        ocp_cfg = {}
    return {"strict_default_deny": bool(ocp_cfg.get("strict_default_deny"))}


def set_ocp_policy(org_extra_data: dict | None, *, strict_default_deny: bool) -> dict:
    """Return new extra_data with OCP policy merged; caller persists."""
    extra = dict(org_extra_data or {})
    ocp_cfg = dict(extra.get("ocp") if isinstance(extra.get("ocp"), dict) else {})
    ocp_cfg["strict_default_deny"] = bool(strict_default_deny)
    extra["ocp"] = ocp_cfg
    return extra


def authorize(
    grants: list[AuthorityGrant],
    action: str,
    *,
    resource_type: str | None = None,
    resource_id: str | None = None,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Deterministic allow/deny. No LLM in the path."""
    for grant in grants:
        if not grant_is_valid(grant, now):
            continue
        if not any(action_matches(p, action) for p in (grant.actions or [])):
            continue
        resources = grant.resources or {}
        allowed_ids = resources.get(resource_type) if resource_type else None
        if allowed_ids and resource_id not in allowed_ids:
            continue
        return True, f"allowed by grant {grant.id} ({grant.role})"
    return False, "no valid grant for action"


def decision_level(change_type: str) -> int:
    return DECISION_LEVEL_BY_CHANGE.get(change_type, 2)


def missing_decision_fields(payload: dict) -> list[str]:
    return [f for f in DECISION_PROTOCOL_FIELDS if not str(payload.get(f, "")).strip()]


def can_approve(level: int, *, is_founder: bool) -> bool:
    """Level 1 needs no approval; levels 2-3 need the Founder."""
    if level <= 1:
        return True
    return is_founder


def decide(record: DecisionRecord, *, approve: bool, founder_id: str) -> DecisionRecord:
    """Founder decision on a fully justified proposal. Records provenance."""
    missing = missing_decision_fields(record.justification or {})
    if missing:
        raise ValueError(f"decision protocol incomplete: missing {', '.join(missing)}")
    record.status = "approved" if approve else "rejected"
    record.decided_by = founder_id
    record.decided_at = _now()
    return record


def _normalize_approval_bridge_status(status: str) -> str:
    normalized = (status or "").strip().lower()
    if not normalized:
        return "unknown"
    if normalized not in APPROVAL_BRIDGE_STATUSES:
        allowed = ", ".join(APPROVAL_BRIDGE_STATUSES)
        raise ValueError(f"invalid approval bridge status: {status!r}; allowed: {allowed}")
    return normalized


def approval_bridge_metadata(record: DecisionRecord) -> dict:
    """Observability-only bridge metadata. Explicitly not core unification."""
    refs = list((record.justification or {}).get("_external_approvals") or [])
    statuses = sorted({str(r.get("status") or "unknown") for r in refs})
    ref_types = sorted({str(r.get("ref_type") or "") for r in refs if r.get("ref_type")})
    return {
        "mode": "external_refs_only",
        "unified": False,
        "external_approval_count": len(refs),
        "statuses": statuses,
        "ref_types": ref_types,
        "latest_linked_at": refs[-1].get("linked_at") if refs else None,
        "limitation": (
            "PendingAction/ApprovalManager↔DecisionRecord unification deferred; "
            "refs stored in justification._external_approvals; no core approval ownership"
        ),
    }


def link_external_approval(
    record: DecisionRecord,
    *,
    ref_type: str,
    ref_id: str,
    status: str = "",
    note: str = "",
    linked_by_type: str = "",
    linked_by_id: str = "",
) -> DecisionRecord:
    """Pragmatic bridge: attach external approval refs without schema change.

    Stores refs in `DecisionRecord.justification["_external_approvals"]`.
    This avoids core approval/runtime ownership; full PendingAction/DecisionRecord
    unification remains deferred.
    """
    ref_type = (ref_type or "").strip().lower()
    ref_id = (ref_id or "").strip()
    if not ref_type or not ref_id:
        raise ValueError("ref_type and ref_id are required")
    if ref_type not in APPROVAL_BRIDGE_REF_TYPES:
        allowed = ", ".join(APPROVAL_BRIDGE_REF_TYPES)
        raise ValueError(f"invalid approval bridge ref_type: {ref_type!r}; allowed: {allowed}")
    normalized_status = _normalize_approval_bridge_status(status)
    justification = dict(record.justification or {})
    refs = list(justification.get("_external_approvals") or [])
    refs.append(
        {
            "ref_type": ref_type,
            "ref_id": ref_id,
            "status": normalized_status,
            "note": (note or "").strip(),
            "linked_at": _now().isoformat(),
            "linked_by_type": (linked_by_type or "").strip(),
            "linked_by_id": (linked_by_id or "").strip(),
        }
    )
    justification["_external_approvals"] = refs
    record.justification = justification
    return record


def execute_decision(
    record: DecisionRecord,
    tasks: list[SharedTask],
    *,
    actor_type: str = "human",
    actor_id: str = "",
) -> DecisionRecord:
    """Approved decision executes linked shared tasks; approval is not enough to skip state checks."""
    if record.status != "approved":
        raise ValueError("only approved decisions execute")
    raw_ids = list(record.linked_task_ids or [])
    linked = {str(tid) for tid in raw_ids if tid is not None}
    if not linked and not any(tid is None for tid in raw_ids):
        raise ValueError("approved decision has no linked tasks")
    reconciled: list[str] = []
    for task in tasks:
        task_id = task.id
        matches = task_id in raw_ids or (task_id is not None and str(task_id) in linked)
        if not matches:
            continue
        if task.status == "ready":
            transition_task(task, "in_progress", actor_type, actor_id, "decision execution")
        task.audit_history = task.audit_history or []
        if task_id is not None:
            reconciled.append(str(task_id))
    if not reconciled and not any(t is not None and (t.id in raw_ids or str(t.id) in linked) for t in tasks):
        raise ValueError("approved decision has no linked tasks in scope")
    record.linked_task_ids = reconciled
    record.status = "executed"
    return record


def task_budget_check(task: SharedTask, budgets: list, *, spent_brl: float = 0.0) -> tuple[str, str]:
    """Task-level budget: task must reference a known budget within its limit."""
    if task.budget_id is None:
        return "unknown", "task has no budget"
    budget = next((b for b in budgets if getattr(b, "id", None) == task.budget_id), None)
    if budget is None:
        return "deny", "task budget not found"
    amount = getattr(budget, "amount_brl", 0.0) or 0.0
    if amount > 0 and spent_brl > amount:
        return "deny", "task budget exceeded"
    return "allow", "task budget within limit"


# §6 lean default departments. Founder activates; no agent workforce created.
DEFAULT_DEPARTMENTS = (
    {"slug": "executive-secretary", "name": "Executive/Secretary", "mission": "Founder interface, meeting preparation, decisions, reporting and organizational memory."},
    {"slug": "commercial", "name": "Commercial", "mission": "LIA, lead research/qualification, outreach preparation and Sales/CRM workflows."},
    {"slug": "operations", "name": "Operations", "mission": "Task coordination, process monitoring and reporting."},
    {"slug": "engineering", "name": "Engineering", "mission": "Architecture, implementation, testing, deployment, maintenance, technical debt, performance and DX."},
    {"slug": "governance", "name": "Governance", "mission": "Optional Privacy/Security evidence and assessments support; no human Encarregado/legal counsel replacement."},
    {"slug": "product", "name": "Product", "mission": "Internal AIOS product development: problem, value, telemetry, journeys, outcomes; peer to Engineering."},
    {"slug": "security-ai-soc", "name": "Security / AI SOC", "mission": "Independent assurance: AppSec, infra, AI security, IAM, ops security, supply chain; deterministic controls."},
    {"slug": "privacy-lgpd", "name": "Privacy & LGPD", "mission": "Independent privacy governance/assurance; controller/operator per purpose/contract; human Encarregado required where applicable."},
)
