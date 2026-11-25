"""Regression tests for plan-limit row locking.

`_is_sqlite` is a coroutine but was called without `await`:

    for_update = "" if _is_sqlite(db) else " FOR UPDATE"

A coroutine object is always truthy, so the condition was always True and
`for_update` was always "". Postgres therefore never got the `FOR UPDATE` the
comment promised, and the read-then-increment of the usage counters ran
unsynchronised across workers -- a tenant could exceed their daily message
limit by racing concurrent requests, while SQLite (single writer) hid the bug
from every local test run.
"""

import asyncio
import warnings
from datetime import date

import pytest

from aios.core import limits


class _FakeSess:
    def __init__(self, dialect_name):
        self._dialect_name = dialect_name

    def get_bind(self):
        outer = self

        class _Dialect:
            name = outer._dialect_name

        class _Bind:
            dialect = _Dialect()

        return _Bind()


class _FakeDB:
    def __init__(self, dialect_name="postgresql", add_error=None):
        self._dialect_name = dialect_name
        self.statements = []
        self.added = []
        self.add_error = add_error
        self.commits = 0

    async def _sess(self):
        return _FakeSess(self._dialect_name)

    async def execute(self, stmt, *a, **k):
        sql = str(stmt)
        self.statements.append(sql)
        # Stop exactly at the usage row read: everything before it (agent counts,
        # plan lookups) is irrelevant to whether the lock is applied.
        if "usage_records" in sql.lower() and sql.lstrip().upper().startswith("SELECT"):
            raise _Stop()
        return _Permissive()

    def add(self, row):
        if self.add_error:
            raise self.add_error
        self.added.append(row)

    async def commit(self):
        self.commits += 1

    async def get(self, model, ident):
        class _Org:
            is_active = True
            extra_data = None
            plan = "pro"
            created_at = None
        return _Org()


class _Stop(Exception):
    pass


class _Permissive:
    """Result stand-in so execution can reach the usage SELECT."""

    def mappings(self):
        return self

    def first(self):
        return {"messages": 0, "llm_tokens": 0, "cost_usd": 0.0}

    def one(self):
        # Aggregate cost query returns (cost_usd, whatsapp_cost_usd).
        return (0, 0)

    def scalar(self):
        return 0

    def scalar_one_or_none(self):
        return None

    def all(self):
        return []

    def fetchall(self):
        return []


class _AggregateResult:
    def __init__(self, row):
        self._row = row

    def one(self):
        return self._row


class _BudgetListResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _AggregateDB(_FakeDB):
    """Runs past the usage lock so the monthly aggregate can be counted."""

    def __init__(self, *, tokens=0, cost=0.0, whatsapp_cost=0.0, budgets=()):
        super().__init__("postgresql")
        self.tokens = tokens
        self.cost = cost
        self.whatsapp_cost = whatsapp_cost
        self.budgets = list(budgets)
        self.aggregate_calls = []

    async def execute(self, stmt, *a, **k):
        sql = str(stmt)
        self.statements.append(sql)
        upper = sql.upper()
        if upper.lstrip().startswith("SELECT"):
            if "SUM(" in upper and "USAGE_RECORDS" in upper:
                self.aggregate_calls.append(sql)
                return _AggregateResult((self.tokens, self.cost, self.whatsapp_cost))
            if "FROM BUDGETS" in upper:
                return _BudgetListResult(self.budgets)
        return _Permissive()


class _Budget:
    def __init__(self, amount_brl):
        self.id = "budget-1"
        self.name = "test-budget"
        self.type = "operation"
        self.scope = {}
        self.amount_brl = amount_brl


@pytest.mark.asyncio
async def test_is_sqlite_awaits_and_reports_dialect():
    assert await limits._is_sqlite(_FakeDB("postgresql")) is False
    assert await limits._is_sqlite(_FakeDB("sqlite")) is True


@pytest.mark.asyncio
async def test_is_sqlite_returns_bool_not_coroutine():
    """A coroutine is truthy; if this ever returns one again the bug is back."""
    result = await limits._is_sqlite(_FakeDB("postgresql"))
    assert isinstance(result, bool)
    assert result is False


@pytest.mark.asyncio
async def test_postgres_limit_check_emits_for_update(monkeypatch):
    """The SELECT that reads today's usage must carry FOR UPDATE on Postgres."""
    monkeypatch.setattr("aios.config.settings.internal_mode", False)
    db = _FakeDB("postgresql")
    with pytest.raises(_Stop):
        await limits.check_org_limits("org-1", db)
    selects = [s for s in db.statements if s.lstrip().upper().startswith("SELECT")]
    assert any("FOR UPDATE" in s for s in selects), selects


@pytest.mark.asyncio
async def test_sqlite_limit_check_omits_for_update(monkeypatch):
    """SQLite rejects FOR UPDATE, so it must stay off there."""
    monkeypatch.setattr("aios.config.settings.internal_mode", False)
    db = _FakeDB("sqlite")
    with pytest.raises(_Stop):
        await limits.check_org_limits("org-1", db)
    selects = [s for s in db.statements if s.lstrip().upper().startswith("SELECT")]
    assert selects, "expected a usage SELECT"
    assert not any("FOR UPDATE" in s for s in selects)


def test_no_never_awaited_coroutine_warning(monkeypatch):
    """The old bug surfaced at runtime as 'coroutine ... was never awaited'."""
    monkeypatch.setattr("aios.config.settings.internal_mode", False)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")

        async def run():
            db = _FakeDB("postgresql")
            with pytest.raises(_Stop):
                await limits.check_org_limits("org-1", db)

        asyncio.run(run())
    assert not [w for w in caught if "never awaited" in str(w.message)]


@pytest.mark.asyncio
async def test_track_usage_persists_attribution_row():
    db = _FakeDB()
    await limits.track_usage(
        "org-1", db, tokens=10, cost_usd=0.01,
        model="openai/gpt-4o-mini", provider="openai",
        input_tokens=6, output_tokens=4,
        attribution={"path": "test"},
    )
    row, = db.added
    assert (row.org_id, row.date) == ("org-1", date.today().isoformat())
    assert (row.model, row.provider, row.cost_kind) == ("openai/gpt-4o-mini", "openai", "internal")
    assert (row.input_tokens, row.output_tokens, row.total_tokens) == (6, 4, 10)
    assert row.cost_usd == 0.01
    assert row.attribution == {"path": "test"}
    assert db.commits == 1


@pytest.mark.asyncio
async def test_track_usage_attribution_failure_keeps_counting():
    db = _FakeDB(add_error=RuntimeError("missing table"))
    await limits.track_usage("org-1", db, model="openai/gpt-4o-mini")
    assert db.added == []
    assert db.statements, "aggregate upsert must still run"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_monthly_usage_is_aggregated_once_across_all_gates(monkeypatch):
    """Token gate, cost guardrail, budget alert and soft warning share one SUM."""
    monkeypatch.setattr("aios.config.settings.internal_mode", False)
    monkeypatch.setattr(limits, "_fx", lambda: 5.5)
    alerts = []

    async def _enqueue(name, payload):
        alerts.append((name, payload))

    monkeypatch.setattr("aios.tasks.queue.enqueue_job", _enqueue)

    plan = limits.PLANS["free"]
    monkeypatch.setitem(plan, "max_tokens_per_month", 1000)
    monkeypatch.setitem(plan, "max_cost_brl", 1000)
    db = _AggregateDB(
        tokens=850, cost=10.0, whatsapp_cost=2.0, budgets=[_Budget(75)]
    )
    assert await limits.check_org_limits("org-1", db) == (True, "")
    assert db.commits == 0, "check_org_limits must not commit caller state"
    assert len(db.aggregate_calls) == 1, db.statements
    assert ("aios.tasks.jobs.quota_alert_job", {
        "org_id": "org-1", "pct": 85.0, "plan": "free",
    }) in alerts
    assert any(
        name == "aios.tasks.jobs.budget_alert_job" and payload["pct"] == 88
        for name, payload in alerts
    ), alerts

    # Token gate reads the same aggregate, with no second SUM.
    monkeypatch.setitem(plan, "max_tokens_per_month", 800)
    token_db = _AggregateDB(tokens=850, cost=10.0, whatsapp_cost=2.0)
    assert await limits.check_org_limits("org-1", token_db) == (
        False, "Monthly token limit reached (800/free plan)"
    )
    assert len(token_db.aggregate_calls) == 1, token_db.statements

    # Cost guardrail reads the same aggregate, with no second SUM.
    monkeypatch.setitem(plan, "max_tokens_per_month", 999999999)
    monkeypatch.setitem(plan, "max_cost_brl", 60)
    cost_db = _AggregateDB(tokens=850, cost=10.0, whatsapp_cost=2.0)
    assert await limits.check_org_limits("org-1", cost_db) == (
        False,
        "Teto custo estimado R$60 atingido (uso R$66.00 no mês) — plano free. Upgrade em /dashboard/billing",
    )
    assert len(cost_db.aggregate_calls) == 1, cost_db.statements