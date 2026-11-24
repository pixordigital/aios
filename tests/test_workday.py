"""Workday board with CRM + OCP task sources, without a database.

Fake rows only: these tests cover which rows reach the board, provenance,
ordering and the agent instruction. SQL filtering (org/status/owner) stays a
property of the query in `board_for_agent`.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from aios.core.workday import board_for_agent, org_workday_enabled, render_board, should_work_day

ORG = "o1"
AGENT = "a1"
NOW = datetime.now(timezone.utc)


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    """Routes each query by the table in the compiled select."""

    def __init__(self, deals=(), tasks=(), members=()):
        self.deals = deals
        self.tasks = tasks
        self.members = members

    async def execute(self, stmt):
        table = getattr(stmt.get_final_froms()[0], "name", "")
        return {
            "crm_deals": _Result(self.deals),
            "shared_tasks": _Result(self.tasks),
            "department_members": _Result(self.members),
        }[table]


def _agent(**kw):
    fields = dict(id=AGENT, org_id=ORG, name="Data Bot", agent_type="data_analyst",
                  status="active", extra_data={})
    fields.update(kw)
    return SimpleNamespace(**fields)


def _deal(id="d1", **kw):
    fields = dict(id=id, org_id=ORG, agent_id=AGENT, lead_name="Lead " + id,
                  lead_email="", lead_phone="", stage="opportunity", source="form",
                  value=1000.0, updated_at=NOW - timedelta(hours=2), extra_data={})
    fields.update(kw)
    return SimpleNamespace(**fields)


def _task(id="t1", **kw):
    fields = dict(id=id, org_id=ORG, title="Tarefa " + id, objective="Objetivo " + id,
                  status="ready", priority=2, owner_type="agent", owner_id=AGENT,
                  responsible_department_id=None, deadline=None,
                  expected_deliverable="Entregável " + id,
                  updated_at=NOW - timedelta(hours=2))
    fields.update(kw)
    return SimpleNamespace(**fields)


async def test_crm_only_board_keeps_its_shape():
    board = await board_for_agent(_agent(), _FakeDB(deals=[_deal()]))

    assert board["count"] == 1
    assert board["items"][0]["source"] == "crm"
    assert board["items"][0]["deal_id"] == "d1"
    assert board["items"][0]["lead"] == "Lead d1"
    assert board["items"][0]["stage"] == "opportunity"
    assert board["items"][0]["timing"] > 0


async def test_agent_owned_task_enters_the_board_with_provenance():
    board = await board_for_agent(
        _agent(),
        _FakeDB(tasks=[_task(objective="Levantar métricas", expected_deliverable="Relatório")]),
    )

    assert board["count"] == 1
    item = board["items"][0]
    assert item["source"] == "task"
    assert item["task_id"] == "t1"
    assert "deal_id" not in item
    assert item["title"] == "Tarefa t1"
    assert item["objective"] == "Levantar métricas"
    assert item["expected_deliverable"] == "Relatório"


async def test_department_task_reaches_the_agent_and_is_not_duplicated():
    # Same task matches owner AND responsible department: one item, not two.
    task = _task(responsible_department_id="dept1")
    board = await board_for_agent(
        _agent(),
        _FakeDB(tasks=[task], members=[SimpleNamespace(department_id="dept1")]),
    )

    assert [i["source"] for i in board["items"]] == ["task"]
    assert [i["task_id"] for i in board["items"]] == ["t1"]
    assert board["count"] == 1


async def test_deadline_due_lifts_task_and_equal_scores_are_stable():
    overdue = _task(id="late", deadline=NOW - timedelta(hours=3))
    # Same updated_at -> same timing; id breaks the tie deterministically.
    tasks = [overdue, _task(id="bbb"), _task(id="aaa")]

    board = await board_for_agent(_agent(), _FakeDB(tasks=tasks))

    assert [i["task_id"] for i in board["items"]] == ["late", "aaa", "bbb"]
    assert board["overdue"] == 1
    assert board["items"][0]["due_overdue"] == overdue.deadline.isoformat()


async def test_boards_mix_sources_in_one_ranked_list():
    board = await board_for_agent(
        _agent(),
        _FakeDB(deals=[_deal(id="d1")], tasks=[_task(id="t1")]),
    )

    assert board["count"] == 2
    assert {i["source"] for i in board["items"]} == {"crm", "task"}
    assert [i["timing"] for i in board["items"]] == sorted(
        (i["timing"] for i in board["items"]), reverse=True
    )


def test_render_board_names_both_sources_and_keeps_crm_only_prompt():
    mixed = render_board(
        {
            "date": "2026-11-24", "count": 2, "overdue": 0,
            "items": [
                {"source": "crm", "deal_id": "d1", "lead": "Ana", "stage": "sql",
                 "value": 5000.0, "timing": 60, "hours_since_touch": 72.0,
                 "next_follow_up": "", "follow_up_note": "", "due_overdue": None,
                 "summary": ""},
                {"source": "task", "task_id": "t1", "title": "Relatório", "status": "ready",
                 "priority": 2, "timing": 50, "hours_since_touch": 2.0,
                 "objective": "Levantar métricas", "expected_deliverable": "Relatório final",
                 "deadline": "", "due_overdue": None},
            ],
        }
    )
    assert "deal_id=d1" in mixed
    assert "source=task | task_id=t1 | Relatório" in mixed
    assert "status=ready" in mixed
    assert "objetivo: Levantar métricas" in mixed
    assert "entregável: Relatório final" in mixed
    assert "tarefas do OCP" in mixed

    crm_only = render_board(
        {
            "date": "2026-11-24", "count": 1, "overdue": 0,
            "items": [{"source": "crm", "deal_id": "d1", "lead": "Ana", "stage": "sql",
                       "value": 5000.0, "timing": 60, "hours_since_touch": 72.0,
                       "next_follow_up": "", "follow_up_note": "", "due_overdue": None,
                       "summary": ""}],
        }
    )
    assert "tarefas do OCP" not in crm_only
    assert "mover o stage no CRM" in crm_only


def test_optouts_and_reactive_exclusion_are_untouched():
    from aios.db.models import Organization

    assert not should_work_day(_agent(agent_type="sdr"))
    assert not should_work_day(_agent(agent_type="support"))
    assert not should_work_day(_agent(status="draft"))
    assert not should_work_day(_agent(extra_data={"workday": False}))
    assert should_work_day(_agent(agent_type="media"))
    assert not org_workday_enabled(Organization(extra_data={"workday_enabled": "true"}))
    assert org_workday_enabled(Organization(extra_data={"workday_enabled": True}))
