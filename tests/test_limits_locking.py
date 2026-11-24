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