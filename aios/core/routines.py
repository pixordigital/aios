"""Read-only routine read model.

Normalizes AutomationTrigger, ARQ cron jobs, fixed scheduler ticks, workday,
and agent event subscriptions into one deterministic shape. No writes, no
enqueue, no scheduler registration.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import or_, select

RoutineMode = Literal["reactive", "proactive", "hybrid"]
RoutineSource = Literal[
    "automation_cron",
    "arq_cron",
    "workday",
    "event_subscription",
    "fixed_tick",
]


@dataclass(frozen=True)
class RoutineReadModel:
    routine_id: str  # stable "source:native_id"
    org_id: str | None
    name: str
    source_type: RoutineSource
    enabled: bool
    schedule_kind: Literal["cron", "interval", "daily_fixed", "event"]
    cron_expr: str | None = None
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    timezone: str = "UTC"
    event_types: list[str] = field(default_factory=list)
    agent_id: str | None = None
    team_id: str | None = None
    workflow_id: str | None = None
    channel_connection_id: str | None = None
    job_name: str | None = None
    entrypoint: str | None = None
    mode: RoutineMode = "proactive"
    last_status: str | None = None
    last_run_id: str | None = None
    source_ref: str | None = None
    notes: list[str] = field(default_factory=list)


ARQ_CRON_CATALOG: dict[str, dict] = {
    "cron_tick_job": {
        "cron_expr": "0 * * * * *",
        "schedule_kind": "interval",
        "name": "Cron trigger tick",
        "entrypoint": "aios.core.cron_scheduler.run_once",
        "source_ref": "aios/tasks/worker.py",
        "notes": ["global", "every minute at second 0"],
    },
    "telemetry_flush_job": {
        "cron_expr": "0 */5 * * * *",
        "schedule_kind": "interval",
        "name": "Telemetry flush",
        "entrypoint": "aios.core.telemetry.telemetry.flush_to_db",
        "source_ref": "aios/tasks/worker.py",
        "notes": ["global", "every 5 minutes"],
    },
    "approval_expire_job": {
        "cron_expr": "0 5 * * * *",
        "schedule_kind": "cron",
        "name": "Approval expiry",
        "entrypoint": "aios.core.approval.approval_manager.cancel_expired",
        "source_ref": "aios/tasks/worker.py",
        "notes": ["global", "hourly at minute 5"],
    },
    "autoscale_job": {
        "cron_expr": "0 0 * * * *",
        "schedule_kind": "cron",
        "name": "Autoscale check",
        "entrypoint": "aios.core.autoscaling.check_autoscale",
        "source_ref": "aios/tasks/worker.py",
        "notes": ["global", "hourly"],
    },
    "canary_rollback_job": {
        "cron_expr": "0 10 * * * *",
        "schedule_kind": "cron",
        "name": "Canary rollback check",
        "entrypoint": "aios.tasks.worker.canary_rollback_job",
        "source_ref": "aios/tasks/worker.py",
        "notes": ["global", "hourly at minute 10"],
    },
    "_pattern_extraction_cron": {
        "cron_expr": "0 30 * * * *",
        "schedule_kind": "cron",
        "name": "Pattern extraction",
        "entrypoint": "aios.tasks.learning_worker.pattern_extraction_job",
        "source_ref": "aios/tasks/worker.py",
        "notes": ["global", "hourly at minute 30"],
    },
    "_memory_consolidation_cron": {
        "cron_expr": "0 0 * * * *",
        "schedule_kind": "cron",
        "name": "Memory consolidation",
        "entrypoint": "aios.tasks.learning_worker.memory_consolidation_job",
        "source_ref": "aios/tasks/worker.py",
        "notes": ["global", "hourly"],
    },
    "_optimization_review_cron": {
        "cron_expr": "0 15 * * * *",
        "schedule_kind": "cron",
        "name": "Optimization review",
        "entrypoint": "aios.tasks.learning_worker.optimization_review_job",
        "source_ref": "aios/tasks/worker.py",
        "notes": ["global", "hourly at minute 15"],
    },
    "_eval_review_cron": {
        "cron_expr": "0 25 * * * *",
        "schedule_kind": "cron",
        "name": "Eval review",
        "entrypoint": "aios.tasks.learning_worker.eval_review_job",
        "source_ref": "aios/tasks/worker.py",
        "notes": ["global", "hourly at minute 25"],
    },
    "template_status_reconcile_job": {
        "cron_expr": "0 23 * * * *",
        "schedule_kind": "cron",
        "name": "Template status reconcile",
        "entrypoint": "aios.tasks.jobs.template_status_reconcile_job",
        "source_ref": "aios/tasks/worker.py",
        "notes": ["global", "hourly at minute 23"],
    },
    "integration_outbox_cron": {
        "cron_expr": "30 * * * * *",
        "schedule_kind": "interval",
        "name": "Integration outbox flush",
        "entrypoint": "aios.integrations.arvo.publisher.flush_outbox",
        "source_ref": "aios/tasks/worker.py",
        "notes": ["global", "every minute at second 30"],
    },
    "event_consume_job": {
        "cron_expr": "0,20,40 * * * * *",
        "schedule_kind": "interval",
        "name": "Event bus consume",
        "entrypoint": "aios.tasks.jobs.event_consume_job",
        "source_ref": "aios/tasks/worker.py",
        "notes": ["global", "every 20 seconds"],
    },
    "workday_job": {
        "cron_expr": "0 0 7 * * *",
        "schedule_kind": "daily_fixed",
        "name": "Agent workday",
        "entrypoint": "aios.tasks.jobs.workday_job",
        "source_ref": "aios/tasks/worker.py",
        "notes": ["global", "07:00 UTC daily"],
    },
    "owner_escalation_job": {
        "cron_expr": "0 */5 * * * *",
        "schedule_kind": "interval",
        "name": "Owner escalation",
        "entrypoint": "aios.tasks.jobs.owner_escalation_job",
        "source_ref": "aios/tasks/worker.py",
        "notes": ["global", "every 5 minutes"],
    },
    "weekly_standup_job": {
        "cron_expr": "0 0 9 * * *",
        "schedule_kind": "daily_fixed",
        "name": "Weekly standup trigger",
        "entrypoint": "aios.tasks.jobs.weekly_standup_job",
        "source_ref": "aios/tasks/worker.py",
        "notes": ["global", "09:00 UTC daily; self-skips unless Monday"],
    },
    "weekly_report_job": {
        "cron_expr": "0 15 9 * * 1",
        "schedule_kind": "cron",
        "name": "Weekly report",
        "entrypoint": "aios.tasks.jobs.weekly_report_job",
        "source_ref": "aios/tasks/worker.py",
        "notes": ["global", "Mondays 09:15 UTC"],
    },
    "monthly_report_job": {
        "cron_expr": "0 30 9 1 * *",
        "schedule_kind": "cron",
        "name": "Monthly report",
        "entrypoint": "aios.tasks.jobs.monthly_report_job",
        "source_ref": "aios/tasks/worker.py",
        "notes": ["global", "1st of month 09:30 UTC"],
    },
    "night_shift_job": {
        "cron_expr": "0 0 3 * * *",
        "schedule_kind": "daily_fixed",
        "name": "Night shift maintenance",
        "entrypoint": "aios.tasks.jobs.night_shift_job",
        "source_ref": "aios/tasks/worker.py",
        "notes": ["global", "03:00 UTC daily", "read-only reporting"],
    },
}


def stable_routine_id(source_type: str, native_id: str) -> str:
    return f"{source_type}:{native_id}"


def infer_mode(*, has_schedule: bool, has_events: bool) -> RoutineMode:
    if has_schedule and has_events:
        return "hybrid"
    if has_events:
        return "reactive"
    return "proactive"


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _get(obj, name: str, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def routine_from_automation_trigger(trig) -> RoutineReadModel:
    trig_type = str(_get(trig, "type", "") or "")
    cron_expr = _get(trig, "cron_expr")
    event_type = _get(trig, "event_type")
    config = _get(trig, "config") or {}
    event_types: list[str] = []
    if event_type:
        event_types = [str(event_type)]
    elif isinstance(config.get("event_types"), list):
        event_types = [str(e) for e in config["event_types"] if e]

    has_schedule = bool(cron_expr) or trig_type == "cron"
    has_events = bool(event_types) or trig_type == "event"
    schedule_kind: Literal["cron", "interval", "daily_fixed", "event"]
    if has_events and not has_schedule:
        schedule_kind = "event"
    else:
        schedule_kind = "cron"

    native_id = str(_get(trig, "id"))
    name = str(_get(trig, "name") or f"automation-{native_id}")
    return RoutineReadModel(
        routine_id=stable_routine_id("automation_cron", native_id),
        org_id=_get(trig, "org_id"),
        name=name,
        source_type="automation_cron",
        enabled=bool(_get(trig, "is_active", False)),
        schedule_kind=schedule_kind,
        cron_expr=str(cron_expr) if cron_expr else None,
        next_run_at=_as_utc(_get(trig, "next_run_at")),
        last_run_at=_as_utc(_get(trig, "last_run_at")),
        timezone=str(config.get("timezone") or "UTC"),
        event_types=event_types,
        agent_id=_get(trig, "agent_id") or config.get("agent_id"),
        team_id=_get(trig, "team_id") or config.get("team_id"),
        workflow_id=_get(trig, "workflow_id"),
        channel_connection_id=_get(trig, "channel_connection_id") or config.get("channel_connection_id"),
        job_name=None,
        entrypoint="aios.tasks.jobs.workflow_run_job",
        mode=infer_mode(has_schedule=has_schedule, has_events=has_events),
        last_status=None,
        last_run_id=None,
        source_ref="aios/db/models.py:AutomationTrigger",
        notes=[],
    )


def routine_from_arq_cron(job_name: str, spec: dict) -> RoutineReadModel:
    data = dict(spec or {})
    schedule_kind = str(data.get("schedule_kind") or "cron")
    if schedule_kind not in {"cron", "interval", "daily_fixed", "event"}:
        schedule_kind = "cron"
    return RoutineReadModel(
        routine_id=stable_routine_id("arq_cron", job_name),
        org_id=None,
        name=str(data.get("name") or job_name),
        source_type="arq_cron",
        enabled=True,
        schedule_kind=schedule_kind,  # type: ignore[arg-type]
        cron_expr=str(data["cron_expr"]) if data.get("cron_expr") else None,
        next_run_at=_as_utc(data.get("next_run_at")),
        last_run_at=_as_utc(data.get("last_run_at")),
        timezone=str(data.get("timezone") or "UTC"),
        event_types=[],
        job_name=job_name,
        entrypoint=str(data.get("entrypoint") or job_name),
        mode="proactive",
        last_status=None,
        last_run_id=None,
        source_ref=str(data.get("source_ref") or "aios/tasks/worker.py"),
        notes=list(data.get("notes") or ["global"]),
    )


def fixed_tick_routines() -> list[RoutineReadModel]:
    specs = [
        {
            "native_id": "backup_tick",
            "name": "Daily backup",
            "cron_expr": "0 0 3 * * *",
            "schedule_kind": "daily_fixed",
            "entrypoint": "aios.core.cron_scheduler._backup_tick",
            "notes": ["global", "03:00 UTC daily"],
        },
        {
            "native_id": "proactive_alerts_tick",
            "name": "Proactive sales alerts",
            "cron_expr": "0 0 8 * * *",
            "schedule_kind": "daily_fixed",
            "entrypoint": "aios.core.cron_scheduler._proactive_alerts_tick",
            "notes": ["global", ">=08:00 UTC daily"],
        },
        {
            "native_id": "crm_mql_stale_tick",
            "name": "CRM MQL stale deals",
            "cron_expr": "0 0 9 * * *",
            "schedule_kind": "daily_fixed",
            "entrypoint": "aios.core.cron_scheduler._crm_mql_stale_tick",
            "notes": ["global", ">=09:00 UTC daily"],
        },
        {
            "native_id": "expire_pending_tick",
            "name": "Expire pending actions",
            "cron_expr": "0 0 2 * * *",
            "schedule_kind": "daily_fixed",
            "entrypoint": "aios.core.cron_scheduler._expire_pending_tick",
            "notes": ["global", "02:00 UTC daily"],
        },
    ]
    out: list[RoutineReadModel] = []
    for spec in specs:
        out.append(
            RoutineReadModel(
                routine_id=stable_routine_id("fixed_tick", spec["native_id"]),
                org_id=None,
                name=spec["name"],
                source_type="fixed_tick",
                enabled=True,
                schedule_kind=spec["schedule_kind"],  # type: ignore[arg-type]
                cron_expr=spec["cron_expr"],
                timezone="UTC",
                job_name=spec["native_id"],
                entrypoint=spec["entrypoint"],
                mode="proactive",
                last_status=None,
                last_run_id=None,
                source_ref="aios/core/cron_scheduler.py",
                notes=list(spec["notes"]),
            )
        )
    return out


def routine_from_workday(agent, org, now=None) -> RoutineReadModel | None:
    from aios.core.workday import org_workday_enabled, should_work_day

    if org is None or not org_workday_enabled(org):
        return None
    if agent is None or not should_work_day(agent):
        return None

    agent_id = str(_get(agent, "id"))
    return RoutineReadModel(
        routine_id=stable_routine_id("workday", agent_id),
        org_id=_get(agent, "org_id") or _get(org, "id"),
        name=f"Workday board: {_get(agent, 'name') or agent_id}",
        source_type="workday",
        enabled=True,
        schedule_kind="daily_fixed",
        cron_expr="0 0 7 * * *",
        timezone="UTC",
        agent_id=agent_id,
        team_id=_get(agent, "team_id"),
        job_name="workday_job",
        entrypoint="aios.tasks.jobs.workday_job",
        mode="proactive",
        last_status=None,
        last_run_id=None,
        source_ref="aios/core/workday.py",
        notes=[],
    )


def routine_from_event_subscription(agent, sub: dict) -> RoutineReadModel:
    from aios.core.events import ev_type_matches  # noqa: F401 - contract anchor

    data = dict(sub or {})
    agent_id = str(_get(agent, "id") or data.get("agent_id") or "")
    sub_id = str(data.get("id") or data.get("subscription_id") or data.get("event_type") or data.get("name") or agent_id)
    raw_events = data.get("event_types")
    if raw_events is None and data.get("event_type"):
        raw_events = [data.get("event_type")]
    event_types = [str(e).strip() for e in (raw_events or []) if str(e).strip()]
    enabled = bool(data.get("enabled", True)) and bool(_get(agent, "status", "active") == "active")
    name = str(data.get("name") or f"Event subscription: {agent_id or sub_id}")
    has_schedule = bool(data.get("cron_expr") or data.get("next_run_at"))
    return RoutineReadModel(
        routine_id=stable_routine_id("event_subscription", f"{agent_id}:{sub_id}"),
        org_id=_get(agent, "org_id") or data.get("org_id"),
        name=name,
        source_type="event_subscription",
        enabled=enabled,
        schedule_kind="event" if not has_schedule else "cron",
        cron_expr=str(data["cron_expr"]) if data.get("cron_expr") else None,
        next_run_at=_as_utc(data.get("next_run_at")),
        last_run_at=_as_utc(data.get("last_run_at")),
        timezone=str(data.get("timezone") or "UTC"),
        event_types=event_types,
        agent_id=agent_id or None,
        team_id=_get(agent, "team_id") or data.get("team_id"),
        workflow_id=data.get("workflow_id"),
        channel_connection_id=data.get("channel_connection_id"),
        job_name=str(data.get("job_name") or "proactive_event_job"),
        entrypoint=str(data.get("entrypoint") or "aios.tasks.jobs.proactive_event_job"),
        mode=infer_mode(has_schedule=has_schedule, has_events=bool(event_types)),
        last_status=None,
        last_run_id=None,
        source_ref=str(data.get("source_ref") or "agent.extra_data.event_subscriptions"),
        notes=[],
    )


def _event_subscriptions_from_agent(agent) -> list[RoutineReadModel]:
    from aios.core.events import subscriptions_for

    out: list[RoutineReadModel] = []
    extra = _get(agent, "extra_data") or {}
    raw = extra.get("event_subscriptions")
    if isinstance(raw, dict):
        # allow dict form {id: {...}} or single subscription dict
        if "event_type" in raw or "event_types" in raw or "id" in raw:
            items = [raw]
        else:
            items = []
            for k, v in raw.items():
                if isinstance(v, dict):
                    vv = dict(v)
                    vv.setdefault("id", k)
                    items.append(vv)
    elif isinstance(raw, list):
        items = list(raw)
    elif isinstance(raw, str):
        items = [raw]
    else:
        items = []

    if not items:
        # Fallback: subscriptions_for returns normalized string patterns.
        for pattern in subscriptions_for(agent):
            items.append({"id": pattern, "event_type": pattern})
    else:
        # normalize plain strings
        norm: list = []
        for item in items:
            if isinstance(item, str):
                norm.append({"id": item, "event_type": item})
            elif isinstance(item, dict):
                norm.append(item)
        items = norm
        if not items:
            for pattern in subscriptions_for(agent):
                items.append({"id": pattern, "event_type": pattern})

    seen: set[str] = set()
    for item in items:
        rm = routine_from_event_subscription(agent, item if isinstance(item, dict) else {"event_type": str(item)})
        if rm.routine_id in seen:
            continue
        seen.add(rm.routine_id)
        out.append(rm)
    return out


def _sort_key(r: RoutineReadModel) -> tuple[str, str, str]:
    return (str(r.source_type), str(r.name).lower(), str(r.routine_id))


async def _last_status_by_job(db, org_id: str, routines: list[RoutineReadModel]) -> dict[str, str]:
    """Derive routine status only from persisted failure/run evidence."""
    from aios.db.models import DeadLetter, IntegrationEvent

    job_names = {str(r.job_name) for r in routines if r.job_name}
    if not job_names:
        return {}
    out: dict[str, str] = {}

    failed_rows = (
        await db.execute(
            select(DeadLetter.job_name).where(
                DeadLetter.status == "failed",
                or_(DeadLetter.org_id == org_id, DeadLetter.org_id.is_(None)),
            ).limit(500)
        )
    ).scalars().all()
    failed_names = {str(name or "") for name in failed_rows}
    for job_name in job_names:
        if any(name == job_name or name.endswith(f".{job_name}") for name in failed_names):
            out[job_name] = "failed"

    if "night_shift_job" in job_names:
        event = (
            await db.execute(
                select(IntegrationEvent.response)
                .where(IntegrationEvent.idempotency_key.like(f"night_shift:{org_id}:%"))
                .order_by(IntegrationEvent.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if isinstance(event, dict):
            summary = event.get("summary") if isinstance(event.get("summary"), dict) else {}
            status = str(summary.get("status") or event.get("status") or "")
            if status in {"failed", "completed_with_failures"}:
                out["night_shift_job"] = "failed"
            elif status in {"ok", "completed"}:
                out.setdefault("night_shift_job", "ok")
            elif status == "started":
                out.setdefault("night_shift_job", "running")
    return out


async def list_routines(
    db,
    org_id: str,
    *,
    agent_id: str | None = None,
    source_type: str | None = None,
    mode: str | None = None,
    include_disabled: bool = False,
) -> list[RoutineReadModel]:
    from aios.db.models import Agent, AutomationTrigger, Organization

    routines: list[RoutineReadModel] = []

    # Automation triggers: org-scoped
    trig_rows = (
        await db.execute(select(AutomationTrigger).where(AutomationTrigger.org_id == org_id))
    ).scalars().all()
    for trig in trig_rows:
        rm = routine_from_automation_trigger(trig)
        routines.append(rm)

    # Org + agents for workday/event subscriptions
    org = await db.get(Organization, org_id)
    agent_rows = (
        await db.execute(select(Agent).where(Agent.org_id == org_id))
    ).scalars().all()

    for agent in agent_rows:
        wd = routine_from_workday(agent, org)
        if wd is not None:
            routines.append(wd)
        routines.extend(_event_subscriptions_from_agent(agent))

    # Global/system routines included in org query
    for job_name, spec in ARQ_CRON_CATALOG.items():
        routines.append(routine_from_arq_cron(job_name, spec))
    routines.extend(fixed_tick_routines())

    status_by_job = await _last_status_by_job(db, org_id, routines)
    routines = [
        replace(r, last_status=status_by_job[r.job_name]) if r.job_name in status_by_job else r
        for r in routines
    ]

    # Filters
    if agent_id is not None:
        routines = [r for r in routines if r.agent_id == agent_id]
    if source_type is not None:
        routines = [r for r in routines if r.source_type == source_type]
    if mode is not None:
        routines = [r for r in routines if r.mode == mode]
    if not include_disabled:
        routines = [r for r in routines if r.enabled]

    # Deterministic ordering
    routines.sort(key=_sort_key)
    return routines


async def get_routine(db, org_id: str, routine_id: str) -> RoutineReadModel | None:
    rows = await list_routines(db, org_id, include_disabled=True)
    for r in rows:
        if r.routine_id == routine_id:
            return r
    return None
