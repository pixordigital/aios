"""wakeup_agent: budget gate + enqueue payload."""
import pytest

from aios.core import scheduler


class _FakeDB:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _install(monkeypatch, usage):
    async def _get_monthly_usage(org_id, db):
        return usage

    jobs = []

    async def _enqueue_job(func, payload, priority="normal", **kw):
        jobs.append((func, payload))
        return True

    import aios.core.limits as limits_mod
    import aios.db.backend as backend_mod
    import aios.tasks.queue as queue_mod

    monkeypatch.setattr(limits_mod, "get_monthly_usage", _get_monthly_usage, raising=False)
    monkeypatch.setattr(backend_mod, "db_session", lambda: _FakeDB(), raising=False)
    monkeypatch.setattr(queue_mod, "enqueue_job", _enqueue_job, raising=False)
    return jobs


@pytest.mark.asyncio
async def test_wakeup_over_budget_skips_enqueue(monkeypatch):
    jobs = _install(monkeypatch, {"over_limit": True})
    res = await scheduler.wakeup_agent("a1", "org-1", "do stuff")
    assert res["ok"] is False and res["skipped"] == "over_budget"
    assert jobs == []


@pytest.mark.asyncio
async def test_wakeup_within_budget_enqueues_proactive_job(monkeypatch):
    jobs = _install(monkeypatch, {"total_cost_usd": 0.1})
    res = await scheduler.wakeup_agent("a1", "org-1", "run ops sweep")
    assert res["ok"] is True and res["agent_id"] == "a1"
    func, payload = jobs[0]
    assert func == "aios.tasks.jobs.proactive_event_job"
    assert payload["agent_id"] == "a1"
    assert payload["event"]["payload"]["instruction"] == "run ops sweep"


@pytest.mark.asyncio
async def test_wakeup_agent_coalesces_within_window(monkeypatch):
    import time as _t

    jobs = _install(monkeypatch, {"total_cost_usd": 0.0})
    r1 = await scheduler.wakeup_agent("a1", "org-1", "step one", coalesce_key="k1")
    assert r1["ok"] and not r1["coalesced"]
    r2 = await scheduler.wakeup_agent("a1", "org-1", "step two", coalesce_key="k1")
    assert r2["ok"] and r2["coalesced"] and r2["count"] == 2
    # Only one job enqueued so far.
    assert len(jobs) == 1
    # Expire the window: next call flushes merged instruction (no double-fire).
    scheduler._pending_wakeups["k1"] = (
        _t.monotonic() - 1, "org-1", 2, "step one\n---\nstep two"
    )
    r3 = await scheduler.wakeup_agent("a1", "org-1", "step three", coalesce_key="k1")
    assert r3["ok"] and len(jobs) == 2
