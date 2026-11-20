"""Simple-mode agents are created as draft and activated only by real deployment."""

import pytest
from sqlalchemy import select

from aios.core.deployment import deploy_and_verify
from aios.core.simple_compiler import compile_plug_and_play_agent
from aios.db.models import Agent, AgentInstance


@pytest.mark.asyncio
async def test_compiled_agent_deploys_verified(test_db_session, test_org):
    compiled = compile_plug_and_play_agent(
        solution_key="whatsapp_atendente",
        name="Bia da Loja",
        business_name="Loja da Maria",
        business_description="Roupas femininas",
    )
    agent = Agent(
        org_id=test_org.id,
        name=compiled["name"],
        agent_type=compiled["agent_type"],
        system_prompt=compiled["system_prompt"],
        llm_config=compiled["llm_config"],
        tools=compiled["tools"],
        memory_config=compiled["memory_config"],
        governance_config=compiled["governance_config"],
        extra_data=compiled["extra_data"],
        status="draft",
    )
    test_db_session.add(agent)
    await test_db_session.commit()

    await deploy_and_verify(test_db_session, agent, test_org.id, user_id="u1")

    assert agent.status == "active"
    inst = (
        await test_db_session.execute(
            select(AgentInstance).where(AgentInstance.agent_id == agent.id)
        )
    ).scalars().one()
    assert inst.status == "running"
    assert inst.extra_data["verified"] is True
