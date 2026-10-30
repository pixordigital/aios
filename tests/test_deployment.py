"""Deployment means verified — not a status flag.

The provider call is stubbed only at the `probe_agent` seam (see conftest); the
real function is exercised with a fake provider for the failure paths.
"""

import pytest
from sqlalchemy import select

from aios.core.agent_health import health_tracker
from aios.core.deployment import (
    AgentNotReady,
    AgentStopped,
    deploy_and_verify,
    deployment_view,
    probe_agent,
    verify_agent,
)
from aios.db.models import Agent, AgentInstance


def _agent(org_id: str, name="Deployable", status="draft", tools=None) -> Agent:
    return Agent(
        org_id=org_id,
        name=name,
        agent_type="custom",
        system_prompt="You are a test agent.",
        llm_config={"model": "openai/gpt-4o-mini", "max_tokens": 64},
        tools=tools or [],
        governance_config={},
        status=status,
    )


@pytest.mark.asyncio
async def test_deploy_records_evidence_and_activates(test_db_session, test_org):
    agent = _agent(test_org.id)
    test_db_session.add(agent)
    await test_db_session.commit()

    result = await deploy_and_verify(test_db_session, agent, test_org.id, user_id="u1")

    assert agent.status == "active"
    assert result["evidence"]["reply"] == "OK"
    inst = (
        await test_db_session.execute(
            select(AgentInstance).where(AgentInstance.agent_id == agent.id)
        )
    ).scalars().one()
    assert inst.status == "running"
    assert inst.extra_data["verified"] is True
    assert inst.extra_data["model"] == "openai/gpt-4o-mini"
    assert inst.extra_data["deployed_by"] == "u1"


@pytest.mark.asyncio
async def test_failed_probe_leaves_draft_and_records_failure(
    test_db_session, test_org, monkeypatch
):
    import aios.core.deployment as deployment

    async def _boom(agent, timeout=None):
        raise AgentNotReady("provider call failed: invalid api key")

    monkeypatch.setattr(deployment, "probe_agent", _boom)

    agent = _agent(test_org.id)
    test_db_session.add(agent)
    await test_db_session.commit()

    with pytest.raises(AgentNotReady):
        await deploy_and_verify(test_db_session, agent, test_org.id, user_id="u1")

    assert agent.status == "draft"
    inst = (
        await test_db_session.execute(
            select(AgentInstance).where(AgentInstance.agent_id == agent.id)
        )
    ).scalars().one()
    assert inst.status == "failed"
    assert inst.extra_data["verified"] is False
    assert "invalid api key" in inst.extra_data["error"]


@pytest.mark.asyncio
async def test_failed_redeploy_does_not_stop_the_working_version(
    test_db_session, test_org, monkeypatch
):
    import aios.core.deployment as deployment

    agent = _agent(test_org.id)
    test_db_session.add(agent)
    await test_db_session.commit()

    await deploy_and_verify(test_db_session, agent, test_org.id, user_id="u1")

    async def _boom(agent, timeout=None):
        raise AgentNotReady("model removed")

    monkeypatch.setattr(deployment, "probe_agent", _boom)

    with pytest.raises(AgentNotReady):
        await deploy_and_verify(test_db_session, agent, test_org.id, user_id="u1")

    await test_db_session.refresh(agent)
    assert agent.status == "active"
    running = (
        await test_db_session.execute(
            select(AgentInstance).where(
                AgentInstance.agent_id == agent.id,
                AgentInstance.status == "running",
            )
        )
    ).scalars().all()
    assert len(running) == 1
    assert running[0].extra_data["verified"] is True


@pytest.mark.asyncio
async def test_stopped_agent_cannot_deploy(test_db_session, test_org):
    agent = _agent(test_org.id)
    test_db_session.add(agent)
    await test_db_session.commit()

    health_tracker.reset(agent.id)
    for _ in range(15):
        health_tracker.record_failure(agent.id, "boom")

    with pytest.raises(AgentStopped):
        await deploy_and_verify(test_db_session, agent, test_org.id)

    health_tracker.reset(agent.id)


@pytest.mark.asyncio
async def test_verify_agent_reprobes_without_changing_status(test_db_session, test_org):
    agent = _agent(test_org.id, status="draft")
    test_db_session.add(agent)
    await test_db_session.commit()

    result = await verify_agent(test_db_session, agent, test_org.id)

    assert agent.status == "draft"
    assert result["evidence"]["reply"] == "OK"
    inst = (
        await test_db_session.execute(
            select(AgentInstance).where(AgentInstance.agent_id == agent.id)
        )
    ).scalars().one()
    assert inst.extra_data["verified"] is True


@pytest.mark.asyncio
async def test_verify_after_failed_canary_becomes_newest_evidence(test_db_session, test_org):
    from datetime import datetime, timezone

    agent = _agent(test_org.id, status="active")
    test_db_session.add(agent)
    await test_db_session.commit()
    test_db_session.add(
        AgentInstance(
            agent_id=agent.id,
            org_id=test_org.id,
            status="failed",
            created_at=datetime(2020, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None),
            extra_data={"verified": False, "error": "canary exploded"},
        )
    )
    await test_db_session.commit()

    await verify_agent(test_db_session, agent, test_org.id)

    history = (
        await test_db_session.execute(
            select(AgentInstance)
            .where(AgentInstance.agent_id == agent.id)
            .order_by(AgentInstance.created_at.desc())
            .limit(5)
        )
    ).scalars().all()
    assert history[0].extra_data["verified"] is True
    assert history[0].extra_data["deploy"] == "verify"
    assert history[1].extra_data["verified"] is False

    view = deployment_view(agent, latest=history[0], history=history)
    assert view["state"] == "verified"
    assert view["history"][1]["result"] == "failed"


def test_deployment_view_states():
    from types import SimpleNamespace

    from aios.db.models import AgentInstance as Inst

    draft = SimpleNamespace(status="draft")
    active = SimpleNamespace(status="active")
    failed = Inst(agent_id="a", org_id="o", status="failed", extra_data={"verified": False, "error": "x"})
    verified = Inst(agent_id="a", org_id="o", status="running", extra_data={"verified": True, "latency_ms": 9})

    assert deployment_view(draft)["state"] == "draft"
    assert deployment_view(active)["state"] == "unverified"
    assert deployment_view(draft, latest=failed)["state"] == "failed"
    assert deployment_view(active, latest=failed)["state"] == "failed_active"
    assert deployment_view(active, latest=verified)["state"] == "verified"


@pytest.mark.asyncio
async def test_real_probe_rejects_empty_prompt_without_calling_provider(test_db_session, test_org):
    agent = _agent(test_org.id)
    agent.system_prompt = "   "
    test_db_session.add(agent)
    await test_db_session.commit()

    with pytest.raises(AgentNotReady, match="system_prompt"):
        await probe_agent(agent)


@pytest.mark.asyncio
async def test_real_probe_reports_empty_provider_response(test_db_session, test_org, monkeypatch):
    agent = _agent(test_org.id)
    test_db_session.add(agent)
    await test_db_session.commit()

    class _FakeLLM:
        async def chat_retry(self, **kwargs):
            return {"content": ""}

    class _FakeRuntime:
        def __init__(self, agent):
            self.llm = _FakeLLM()

    import aios.core.agent as agent_module

    monkeypatch.setattr(agent_module, "AgentRuntime", _FakeRuntime)

    with pytest.raises(AgentNotReady, match="empty response"):
        await probe_agent(agent)


@pytest.mark.asyncio
async def test_health_rows_are_org_scoped(test_db_session, test_org):
    from aios.api.analytics import _agent_health_rows
    from aios.db.models import Organization

    other = Organization(name="Other Org", slug="other-org", extra_data={"plan": "pro"})
    test_db_session.add(other)
    await test_db_session.commit()

    mine = _agent(test_org.id, status="active")
    theirs = _agent(other.id, name="Not Mine", status="active")
    test_db_session.add_all([mine, theirs])
    await test_db_session.commit()

    test_db_session.add(
        AgentInstance(
            agent_id=mine.id,
            org_id=test_org.id,
            status="running",
            extra_data={"verified": True, "verified_at": "2026-01-01T00:00:00+00:00", "latency_ms": 12},
        )
    )
    await test_db_session.commit()

    rows = await _agent_health_rows(test_db_session, test_org.id)

    assert [r["agent_id"] for r in rows] == [mine.id]
    assert rows[0]["deploy_status"] == "verified"
    assert rows[0]["status"] == "no_traffic"
