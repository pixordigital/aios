"""Fleet verification runs per org in the background, not in the request."""

import pytest
from sqlalchemy import select

import aios.core.fleet_verify as fv
from aios.core.fleet_verify import (
    FleetVerifyError,
    cancel_fleet_verification,
    get_fleet_state,
    run_fleet_verification,
    start_fleet_verification,
)
from aios.db.models import Agent, AgentInstance, Organization


def _agent(org_id: str, name: str, status: str = "active") -> Agent:
    return Agent(
        org_id=org_id,
        name=name,
        agent_type="custom",
        system_prompt="You are a test agent.",
        llm_config={"model": "openai/gpt-4o-mini", "max_tokens": 64},
        tools=[],
        governance_config={},
        status=status,
    )


class _Job:
    job_id = "job-1"


@pytest.fixture(autouse=True)
def _memory(monkeypatch):
    """Force the in-memory state store; Redis is not available in tests."""
    fv._MEM.clear()
    fv._LOCKS.clear()
    fv._TASKS.clear()

    async def _no_redis():
        return None

    monkeypatch.setattr(fv, "_redis", _no_redis)
    yield
    fv._MEM.clear()
    fv._LOCKS.clear()
    fv._TASKS.clear()


@pytest.mark.asyncio
async def test_start_only_queues_active_agents_of_the_org(
    test_db_session, test_org, monkeypatch
):
    other = Organization(name="Other", slug="other-org", extra_data={"plan": "pro"})
    test_db_session.add(other)
    await test_db_session.commit()

    keep = [_agent(test_org.id, "A"), _agent(test_org.id, "B")]
    draft = _agent(test_org.id, "Draft", status="draft")
    foreign = _agent(other.id, "Foreign")
    test_db_session.add_all([*keep, draft, foreign])
    await test_db_session.commit()

    calls = []

    async def _enqueue(name, payload, **kwargs):
        calls.append((name, payload, kwargs))
        return _Job()

    monkeypatch.setattr(fv, "enqueue_task", _enqueue)

    state = await start_fleet_verification(test_db_session, test_org.id, "u1")

    assert state["status"] == "queued"
    assert state["runner"] == "redis"
    assert state["job_id"] == "job-1"
    assert state["total"] == 2
    assert state["done"] == 0
    assert len(calls) == 1
    name, payload, kwargs = calls[0]
    assert name == "aios.tasks.jobs.verify_fleet_job"
    assert set(payload["agent_ids"]) == {a.id for a in keep}
    assert payload["org_id"] == test_org.id
    assert kwargs["_job_timeout"] == 900


@pytest.mark.asyncio
async def test_second_start_while_running_is_idempotent(
    test_db_session, test_org, monkeypatch
):
    test_db_session.add(_agent(test_org.id, "A"))
    await test_db_session.commit()

    calls = []

    async def _enqueue(name, payload, **kwargs):
        calls.append(name)
        return _Job()

    monkeypatch.setattr(fv, "enqueue_task", _enqueue)

    first = await start_fleet_verification(test_db_session, test_org.id)
    second = await start_fleet_verification(test_db_session, test_org.id)

    assert first["status"] == "queued"
    assert second["status"] == "queued"
    assert second["job_id"] == "job-1"
    assert len(calls) == 1
    assert _enqueue  # keeps the fake referenced for clarity


@pytest.mark.asyncio
async def test_no_active_agents_raises_and_releases_the_lock(
    test_db_session, test_org, monkeypatch
):
    draft = _agent(test_org.id, "Draft", status="draft")
    test_db_session.add(draft)
    await test_db_session.commit()

    async def _enqueue(name, payload, **kwargs):
        return _Job()

    monkeypatch.setattr(fv, "enqueue_task", _enqueue)

    with pytest.raises(FleetVerifyError, match="no active agents"):
        await start_fleet_verification(test_db_session, test_org.id)

    draft.status = "active"
    await test_db_session.commit()

    state = await start_fleet_verification(test_db_session, test_org.id)
    assert state["total"] == 1


@pytest.mark.asyncio
async def test_run_verifies_every_agent_and_persists_evidence(
    test_db_session, test_org
):
    agents = [_agent(test_org.id, "A"), _agent(test_org.id, "B")]
    test_db_session.add_all(agents)
    await test_db_session.commit()

    state = await run_fleet_verification(
        {
            "org_id": test_org.id,
            "agent_ids": [a.id for a in agents],
            "user_id": "u1",
        }
    )

    assert state["status"] == "done"
    assert (state["done"], state["ok"], state["failed"]) == (2, 2, 0)
    assert {r["name"] for r in state["results"]} == {"A", "B"}
    assert state["finished_at"]

    instances = (
        await test_db_session.execute(
            select(AgentInstance).where(
                AgentInstance.agent_id.in_([a.id for a in agents])
            )
        )
    ).scalars().all()
    assert len(instances) == 2
    assert all(i.extra_data["verified"] is True for i in instances)
    assert all(i.extra_data["deploy"] == "verify" for i in instances)


@pytest.mark.asyncio
async def test_run_records_failure_and_marks_agent_unverified(
    test_db_session, test_org, monkeypatch
):
    import aios.core.deployment as deployment

    agent = _agent(test_org.id, "Broken")
    test_db_session.add(agent)
    await test_db_session.commit()

    async def _fail(agent, timeout=None):
        raise TimeoutError("provider did not answer")

    monkeypatch.setattr(deployment, "probe_agent", _fail)

    state = await run_fleet_verification(
        {"org_id": test_org.id, "agent_ids": [agent.id], "user_id": "u1"}
    )

    assert (state["done"], state["ok"], state["failed"]) == (1, 0, 1)
    assert "did not answer" in state["results"][0]["error"]

    instance = (
        await test_db_session.execute(
            select(AgentInstance).where(AgentInstance.agent_id == agent.id)
        )
    ).scalars().one()
    assert instance.extra_data["verified"] is False
    assert instance.extra_data["deploy"] == "verify"

    # the agent keeps running; only the evidence says the probe failed
    fresh = await test_db_session.get(Agent, agent.id)
    assert fresh.status == "active"


@pytest.mark.asyncio
async def test_cancel_marks_run_cancelled_and_verifies_nothing(
    test_db_session, test_org
):
    agent = _agent(test_org.id, "A")
    test_db_session.add(agent)
    await test_db_session.commit()

    await fv._save(
        {
            "org_id": test_org.id,
            "job_id": "job-1",
            "status": "running",
            "runner": "redis",
            "total": 1,
            "done": 0,
            "ok": 0,
            "failed": 0,
            "started_at": fv._now(),
            "finished_at": None,
            "cancel_requested": False,
            "results": [],
        }
    )

    cancelled = await cancel_fleet_verification(test_org.id)
    assert cancelled["status"] == "cancelling"
    assert cancelled["cancel_requested"] is True

    state = await run_fleet_verification(
        {"org_id": test_org.id, "agent_ids": [agent.id]}
    )

    assert state["status"] == "cancelled"
    assert state["done"] == 0
    rows = (
        await test_db_session.execute(
            select(AgentInstance).where(AgentInstance.agent_id == agent.id)
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_in_process_fallback_runs_when_enqueue_is_unavailable(
    test_db_session, test_org, monkeypatch
):
    test_db_session.add(_agent(test_org.id, "A"))
    await test_db_session.commit()

    async def _no_redis(*args, **kwargs):
        return None

    monkeypatch.setattr(fv, "enqueue_task", _no_redis)

    state = await start_fleet_verification(test_db_session, test_org.id)

    assert state["runner"] == "in-process"
    for task in list(fv._TASKS):
        await task
    finished = await get_fleet_state(test_org.id)
    assert finished["status"] == "done"
    assert finished["ok"] == 1
