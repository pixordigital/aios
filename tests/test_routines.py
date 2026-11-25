from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from aios.core.routines import (
    ARQ_CRON_CATALOG,
    RoutineReadModel,
    fixed_tick_routines,
    get_routine,
    infer_mode,
    list_routines,
    routine_from_arq_cron,
    routine_from_automation_trigger,
    routine_from_event_subscription,
    routine_from_workday,
    stable_routine_id,
)


class _Scalars:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return _Scalars(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, *, triggers=None, agents=None, org=None, dlq_job_names=None, night_event=None):
        self.triggers = list(triggers or [])
        self.agents = list(agents or [])
        self.org = org
        self.dlq_job_names = list(dlq_job_names or [])
        self.night_event = night_event

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        name = getattr(entity, "__name__", "")
        if name == "AutomationTrigger":
            return _Result(self.triggers)
        if name == "Agent":
            return _Result(self.agents)
        if name == "DeadLetter":
            return _Result(self.dlq_job_names)
        if name == "IntegrationEvent":
            return _Result([self.night_event] if self.night_event is not None else [])
        raise AssertionError(f"unexpected query: {name}")

    async def get(self, model, pk):
        if getattr(model, "__name__", "") == "Organization":
            if self.org and getattr(self.org, "id", None) == pk:
                return self.org
        return None


def _agent(**kw):
    base = dict(
        id="a1",
        org_id="o1",
        name="Agent One",
        agent_type="closer",
        status="active",
        extra_data={},
        team_id=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _org(**kw):
    base = dict(id="o1", name="Org", extra_data={"workday_enabled": True})
    base.update(kw)
    return SimpleNamespace(**base)


def _trigger(**kw):
    base = dict(
        id="t1",
        org_id="o1",
        workflow_id="wf1",
        type="cron",
        name="Daily cron",
        is_active=True,
        config={"timezone": "America/Sao_Paulo", "agent_id": "a1", "team_id": "tm1", "channel_connection_id": "cc1"},
        cron_expr="0 9 * * *",
        event_type=None,
        last_run_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        next_run_at=datetime(2026, 1, 2, 9, 0, tzinfo=timezone.utc),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_stable_routine_id():
    assert stable_routine_id("automation_cron", "abc") == "automation_cron:abc"


def test_infer_mode():
    assert infer_mode(has_schedule=True, has_events=False) == "proactive"
    assert infer_mode(has_schedule=False, has_events=True) == "reactive"
    assert infer_mode(has_schedule=True, has_events=True) == "hybrid"


def test_routine_from_automation_trigger_maps_fields():
    rm = routine_from_automation_trigger(_trigger())
    assert rm.routine_id == "automation_cron:t1"
    assert rm.org_id == "o1"
    assert rm.name == "Daily cron"
    assert rm.source_type == "automation_cron"
    assert rm.enabled is True
    assert rm.schedule_kind == "cron"
    assert rm.cron_expr == "0 9 * * *"
    assert rm.timezone == "America/Sao_Paulo"
    assert rm.agent_id == "a1"
    assert rm.team_id == "tm1"
    assert rm.workflow_id == "wf1"
    assert rm.channel_connection_id == "cc1"
    assert rm.mode == "proactive"
    assert rm.last_status is None
    assert rm.last_run_id is None
    assert rm.source_ref == "aios/db/models.py:AutomationTrigger"


def test_routine_from_arq_cron_uses_catalog():
    assert "cron_tick_job" in ARQ_CRON_CATALOG
    rm = routine_from_arq_cron("cron_tick_job", ARQ_CRON_CATALOG["cron_tick_job"])
    assert rm.routine_id == "arq_cron:cron_tick_job"
    assert rm.org_id is None
    assert rm.source_type == "arq_cron"
    assert rm.cron_expr
    assert rm.source_ref == "aios/tasks/worker.py"
    assert "global" in rm.notes
    assert rm.last_status is None and rm.last_run_id is None


def test_arq_catalog_has_known_jobs():
    for name in [
        "cron_tick_job",
        "workday_job",
        "event_consume_job",
        "owner_escalation_job",
        "weekly_standup_job",
        "weekly_report_job",
        "monthly_report_job",
    ]:
        assert name in ARQ_CRON_CATALOG
        assert ARQ_CRON_CATALOG[name]["source_ref"] == "aios/tasks/worker.py"


def test_fixed_tick_routines_present():
    rms = fixed_tick_routines()
    by_id = {r.routine_id: r for r in rms}
    assert "fixed_tick:backup_tick" in by_id
    assert "fixed_tick:proactive_alerts_tick" in by_id
    assert "fixed_tick:crm_mql_stale_tick" in by_id
    assert "fixed_tick:expire_pending_tick" in by_id
    assert by_id["fixed_tick:backup_tick"].cron_expr == "0 0 3 * * *"
    assert by_id["fixed_tick:proactive_alerts_tick"].notes == ["global", ">=08:00 UTC daily"]
    assert all(r.org_id is None and r.source_type == "fixed_tick" for r in rms)
    assert all(r.source_ref == "aios/core/cron_scheduler.py" for r in rms)


def test_workday_routine_only_for_eligible_agents():
    org = _org(extra_data={"workday_enabled": True})
    assert routine_from_workday(_agent(agent_type="closer"), org) is not None
    assert routine_from_workday(_agent(agent_type="sdr"), org) is None
    assert routine_from_workday(_agent(agent_type="support"), org) is None
    assert routine_from_workday(_agent(status="inactive"), org) is None
    assert routine_from_workday(_agent(extra_data={"workday": False}), org) is None
    org_off = _org(extra_data={"workday_enabled": False})
    assert routine_from_workday(_agent(agent_type="closer"), org_off) is None


def test_event_subscription_reactive_and_hybrid():
    reactive = routine_from_event_subscription(_agent(id="a2"), {"id": "sub1", "event_types": ["message.received"]})
    assert reactive.source_type == "event_subscription"
    assert reactive.schedule_kind == "event"
    assert reactive.mode == "reactive"
    assert reactive.event_types == ["message.received"]
    assert reactive.last_status is None and reactive.last_run_id is None

    hybrid = routine_from_event_subscription(
        _agent(id="a3"), {"id": "sub2", "event_types": ["crm.updated"], "cron_expr": "0 * * * *"}
    )
    assert hybrid.mode == "hybrid"
    assert hybrid.schedule_kind == "cron"


def test_routine_dataclass_contract_fields():
    rm = RoutineReadModel(
        routine_id="source:native",
        org_id=None,
        name="n",
        source_type="arq_cron",
        enabled=True,
        schedule_kind="cron",
    )
    assert rm.timezone == "UTC"
    assert rm.event_types == []
    assert rm.notes == []
    assert rm.mode == "proactive"


@pytest.mark.asyncio
async def test_list_routines_filters_ordering_and_global_inclusion():
    org = _org(id="o1")
    triggers = [
        _trigger(id="t2", name="Zulu", is_active=False),
        _trigger(id="t1", name="Alpha", is_active=True),
    ]
    agents = [
        _agent(id="a1", name="Closer", agent_type="closer", extra_data={"event_subscriptions": [{"id": "ev1", "event_types": ["deal.won"]}]}),
        _agent(id="a2", name="SDR", agent_type="sdr", extra_data={"event_subscriptions": [{"id": "ev2", "event_types": ["lead.new"]}]}),
    ]
    db = _FakeDB(triggers=triggers, agents=agents, org=org)

    rows = await list_routines(db, "o1", include_disabled=False)
    ids = [r.routine_id for r in rows]
    assert "automation_cron:t2" not in ids  # disabled filtered
    assert "automation_cron:t1" in ids
    # global routines included
    assert any(r.source_type == "arq_cron" and r.org_id is None for r in rows)
    assert any(r.source_type == "fixed_tick" and r.org_id is None for r in rows)
    # workday only for eligible closer, not sdr
    assert "workday:a1" in ids
    assert "workday:a2" not in ids
    # event subscriptions present
    assert "event_subscription:a1:ev1" in ids
    assert "event_subscription:a2:ev2" in ids
    # no agent_events source
    assert all(r.source_type != "agent_events" for r in rows)
    # deterministic ordering
    keys = [(r.source_type, r.name.lower(), r.routine_id) for r in rows]
    assert keys == sorted(keys)


@pytest.mark.asyncio
async def test_list_routines_last_status_comes_from_persisted_evidence():
    db = _FakeDB(
        triggers=[],
        agents=[],
        org=_org(),
        dlq_job_names=["aios.tasks.jobs.night_shift_job"],
        night_event={"status": "completed", "summary": {"status": "completed_with_failures"}},
    )
    rows = await list_routines(db, "o1", include_disabled=True)
    night = next(r for r in rows if r.routine_id == "arq_cron:night_shift_job")
    assert night.last_status == "failed"
    backup = next(r for r in rows if r.routine_id == "fixed_tick:backup_tick")
    assert backup.last_status is None


@pytest.mark.asyncio
async def test_list_routines_agent_source_mode_filters_and_get():
    org = _org(id="o1")
    agents = [
        _agent(id="a1", agent_type="closer", extra_data={"event_subscriptions": [{"id": "ev1", "event_types": ["deal.won"]}]}),
        _agent(id="a2", agent_type="closer", extra_data={}),
    ]
    db = _FakeDB(triggers=[], agents=agents, org=org)

    only_a1 = await list_routines(db, "o1", agent_id="a1", include_disabled=True)
    assert only_a1
    assert all(r.agent_id == "a1" or r.org_id is None for r in only_a1)
    # agent filter should keep only agent-owned + not global? spec says agent_id filter; global has agent_id None, so exclude
    assert all(r.agent_id == "a1" for r in only_a1)

    only_events = await list_routines(db, "o1", source_type="event_subscription", include_disabled=True)
    assert only_events and all(r.source_type == "event_subscription" for r in only_events)

    reactive = await list_routines(db, "o1", mode="reactive", include_disabled=True)
    assert reactive and all(r.mode == "reactive" for r in reactive)

    got = await get_routine(db, "o1", "workday:a1")
    assert got is not None
    assert got.routine_id == "workday:a1"
    assert await get_routine(db, "o1", "missing:x") is None
