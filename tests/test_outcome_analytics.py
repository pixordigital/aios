"""Business outcome endpoint: counts real rows, labels attribution honestly."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from aios.db.models import Agent, Conversation, CrmDeal, Message, PendingAction


@pytest.mark.asyncio(loop_scope="function")
async def test_outcomes_counts_and_labels_attribution(
    auth_client: AsyncClient, test_session: AsyncSession, test_org
):
    agent = Agent(name="SDR", org_id=test_org.id)
    test_session.add(agent)
    await test_session.flush()

    answered = Conversation(org_id=test_org.id, channel="whatsapp", agent_id=agent.id)
    silent = Conversation(org_id=test_org.id, channel="whatsapp", agent_id=agent.id)
    test_session.add_all([answered, silent])
    await test_session.flush()

    test_session.add_all(
        [
            Message(conversation_id=answered.id, org_id=test_org.id, role="user", content="oi"),
            Message(
                conversation_id=answered.id,
                org_id=test_org.id,
                role="assistant",
                content="olá",
                agent_id=agent.id,
            ),
            Message(conversation_id=silent.id, org_id=test_org.id, role="user", content="oi"),
            CrmDeal(org_id=test_org.id, lead_name="A", value=120.0, agent_id=agent.id),
            CrmDeal(org_id=test_org.id, lead_name="B", value=80.0, agent_id=None),
            PendingAction(
                org_id=test_org.id,
                agent_id=agent.id,
                conversation_id=answered.id,
                tool_name="send_whatsapp",
            ),
        ]
    )
    await test_session.commit()

    response = await auth_client.get("/api/analytics/outcomes")
    assert response.status_code == 200
    data = response.json()

    assert data["enquiries"] == 2
    assert data["answered"] == 1
    assert data["unanswered"] == 1
    assert data["answered_pct"] == 50.0
    assert data["qualified_leads"] == 2
    assert data["deals_attributed"] == 1
    assert data["attributed_value_brl"] == 120.0
    assert data["human_handoffs"] == 1
    assert data["attribution_source"] == "crm_deal.agent_id"
    assert data["attribution_confidence"] == "medium"
    assert data["avg_first_response_seconds"] is not None
