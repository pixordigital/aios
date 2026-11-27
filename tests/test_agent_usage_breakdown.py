"""Phase 3: agent-level usage/cost breakdown."""

import pytest

from aios.core.limits import get_agent_usage_breakdown
from aios.db.models import Agent, AgentMetric


@pytest.mark.asyncio(loop_scope="function")
async def test_agent_usage_breakdown_aggregates_per_agent(auth_client, test_db_session, test_org, test_user):
    agent_sdr = Agent(
        org_id=test_org.id,
        name="SDR Vendedor",
        agent_type="sdr",
        llm_config={"model": "openai/gpt-4o-mini"},
        system_prompt="p",
        tools=[],
        governance_config={},
    )
    agent_closer = Agent(
        org_id=test_org.id,
        name="Closer",
        agent_type="closer",
        llm_config={"model": "openai/gpt-4o-mini"},
        system_prompt="p",
        tools=[],
        governance_config={},
    )
    test_db_session.add_all([agent_sdr, agent_closer])
    await test_db_session.commit()
    await test_db_session.refresh(agent_sdr)
    await test_db_session.refresh(agent_closer)

    test_db_session.add_all(
        [
            AgentMetric(
                agent_id=agent_sdr.id,
                org_id=test_org.id,
                hour="2026-11-20-09",
                messages=2,
                tokens=30,
                errors=0,
                avg_response_ms=10,
                samples=1,
            ),
            AgentMetric(
                agent_id=agent_closer.id,
                org_id=test_org.id,
                hour="2026-11-20-10",
                messages=5,
                tokens=50,
                errors=0,
                avg_response_ms=10,
                samples=1,
            ),
        ]
    )
    await test_db_session.commit()

    rows = await get_agent_usage_breakdown(test_org.id, test_db_session)
    assert len(rows) == 2
    by_id = {r["agent_id"]: r for r in rows}
    assert by_id[agent_sdr.id]["tokens"] == 30
    assert by_id[agent_sdr.id]["name"] == "SDR Vendedor"
    assert by_id[agent_closer.id]["tokens"] == 50
    assert by_id[agent_closer.id]["name"] == "Closer"
    assert [r["agent_id"] for r in rows] == [agent_closer.id, agent_sdr.id]
