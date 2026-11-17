"""The paid path end to end: contract -> runtime -> approval -> outcome.

The pieces existed separately (contract tests, approval API tests). This walks
the path a paying workflow actually takes, so a break in the middle shows up:

    workflow_class -> contract enforced -> runtime bound -> PendingAction
    -> human decision from the dashboard -> counted in /api/analytics/outcomes

Also covers the two read-only surfaces added for the buyer: the approvals page
and the contract viewer, plus the unit-cost endpoint they are priced from.
"""

import contextlib
from datetime import datetime, timedelta, timezone

import pytest

from aios.core.agent import AgentRuntime
from aios.db.engine import async_session
from aios.db.models import (
    Agent,
    Conversation,
    CrmDeal,
    PendingAction,
    UsageRecord,
)
from aios.verticals.pet_business.workflows import LEAD_CAPTURE


@contextlib.asynccontextmanager
async def _cookie(client, user):
    """Dashboard routes authenticate by cookie, not bearer."""
    import jwt

    from aios.api.deps import COOKIE_NAME

    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": user.id,
            "org": user.org_id,
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=60),
        },
        "test-secret",
        algorithm="HS256",
    )
    client.cookies.set(COOKIE_NAME, token)
    try:
        yield
    finally:
        client.cookies.clear()


def _agent(**overrides) -> Agent:
    data = {
        "id": "agent-paid-1",
        "name": "pet-lead-capture",
        "org_id": "org-1",
        "llm_config": {"model": "openai/gpt-4o"},
        "tools": ["rag_search", "web_search", "execute_code", "notify_human"],
        "governance_config": {},
        "extra_data": {},
    }
    data.update(overrides)
    return Agent(**data)


# ─── contract gate ───


def test_paid_workflow_without_contract_refuses():
    agent = _agent(extra_data={"workflow_class": "pet_vet_triage"})
    with pytest.raises(Exception) as exc:
        AgentRuntime(agent)
    assert "not owned by any vertical contract" in str(exc.value)


def test_paid_workflow_without_icm_binding_refuses():
    agent = _agent(extra_data={"workflow_class": "pet_lead_capture"})
    with pytest.raises(Exception) as exc:
        AgentRuntime(agent)
    assert "requires extra_data['icm']" in str(exc.value)


def test_paid_workflow_binds_contract_and_restricts_tools():
    agent = _agent(
        extra_data={
            "workflow_class": "pet_lead_capture",
            "icm": {"stage_id": "pet_lead_capture", "stage_manifest": LEAD_CAPTURE.model_dump()},
        }
    )
    runtime = AgentRuntime(agent)

    assert runtime.stage is not None
    assert runtime.stage.manifest.id == "pet_lead_capture"
    # Denylist from the contract is enforced on top of the agent's own policy.
    assert "execute_code" in runtime._denied_tools
    # Allowlist is intersected: only tools both the agent and the contract allow.
    # "__all__" means the contract allowlist becomes the whole policy; the
    # agent's own `tools` list only narrows what the ToolEngine exposes.
    assert runtime._allowed_tools == set(LEAD_CAPTURE.allowed_tools)
    assert runtime._stage_timeout == LEAD_CAPTURE.timeout_seconds


# ─── approval from the dashboard ───


@pytest.mark.asyncio(loop_scope="function")
async def test_dashboard_approve_writes_decision_and_counts_handoff(
    auth_client, test_session, test_org, test_user
):
    conv = Conversation(org_id=test_org.id, channel="whatsapp")
    test_session.add(conv)
    await test_session.flush()
    action = PendingAction(
        org_id=test_org.id,
        agent_id="agent-paid-1",
        conversation_id=conv.id,
        tool_name="notify_human",
        tool_args={"reason": "clinically sensitive"},
    )
    test_session.add(action)
    await test_session.commit()
    action_id = action.id

    async with _cookie(auth_client, test_user):
        page = await auth_client.get("/dashboard/approvals")
        assert page.status_code == 200
        assert "notify_human" in page.text

        resp = await auth_client.post(
            f"/dashboard/approvals/{action_id}/approve",
            headers={"referer": "http://test/dashboard/approvals"},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    # Read through a fresh session: the dashboard wrote on its own connection.
    async with async_session() as sess:
        row = await sess.get(PendingAction, action_id)
    assert row.status == "approved"
    assert row.decided_by == test_user.id
    assert row.decided_at is not None

    outcomes = await auth_client.get("/api/analytics/outcomes")
    assert outcomes.status_code == 200
    assert outcomes.json()["human_handoffs"] == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_dashboard_reject_writes_decision(auth_client, test_session, test_org, test_user):
    action = PendingAction(
        org_id=test_org.id,
        agent_id="agent-paid-1",
        conversation_id="conv-1",
        tool_name="send_whatsapp",
    )
    test_session.add(action)
    await test_session.commit()
    action_id = action.id

    async with _cookie(auth_client, test_user):
        resp = await auth_client.post(
            f"/dashboard/approvals/{action_id}/reject",
            headers={"referer": "http://test/dashboard/approvals"},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    async with async_session() as sess:
        row = await sess.get(PendingAction, action_id)
    assert row.status == "rejected"
    assert row.decided_by == test_user.id


@pytest.mark.asyncio(loop_scope="function")
async def test_approve_cannot_cross_tenant(auth_client, test_session, test_user):
    other = PendingAction(
        org_id="other-org",
        agent_id="agent-x",
        conversation_id="conv-x",
        tool_name="send_whatsapp",
    )
    test_session.add(other)
    await test_session.commit()
    other_id = other.id

    async with _cookie(auth_client, test_user):
        resp = await auth_client.post(
            f"/dashboard/approvals/{other_id}/approve",
            headers={"referer": "http://test/dashboard/approvals"},
            follow_redirects=False,
        )
        assert resp.status_code == 303  # no leak: just nothing to approve

    async with async_session() as sess:
        row = await sess.get(PendingAction, other_id)
    assert row.status == "pending"
    assert row.decided_by is None


# ─── contract viewer ───


@pytest.mark.asyncio(loop_scope="function")
async def test_contracts_page_shows_contract_and_governed_agent(
    auth_client, test_session, test_org, test_user
):
    test_session.add(
        Agent(
            name="pet-lead-capture",
            org_id=test_org.id,
            extra_data={
                "workflow_class": "pet_lead_capture",
                "icm": {"stage_id": "pet_lead_capture"},
            },
        )
    )
    await test_session.commit()

    async with _cookie(auth_client, test_user):
        page = await auth_client.get("/dashboard/contracts")
    assert page.status_code == 200
    assert "pet_lead_capture" in page.text
    assert "pet_lead_follow_up" in page.text
    assert "pet-lead-capture" in page.text


# ─── unit cost ───


@pytest.mark.asyncio(loop_scope="function")
async def test_unit_cost_reports_no_data_honestly(auth_client):
    resp = await auth_client.get("/api/analytics/unit-cost")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_cost_data"] is False
    assert data["cost_per_conversation_brl"] is None
    assert data["cost_per_qualified_lead_brl"] is None


@pytest.mark.asyncio(loop_scope="function")
async def test_unit_cost_divides_persisted_spend(auth_client, test_session, test_org):
    today = datetime.now(timezone.utc).date().isoformat()
    test_session.add(
        UsageRecord(
            org_id=test_org.id,
            date=today,
            messages=10,
            llm_tokens=5000,
            llm_calls=5,
            cost_usd=1.0,
            whatsapp_messages=4,
            whatsapp_cost_usd=0.1,
        )
    )
    test_session.add_all(
        [
            Conversation(org_id=test_org.id, channel="whatsapp"),
            Conversation(org_id=test_org.id, channel="whatsapp"),
            CrmDeal(org_id=test_org.id, lead_name="A", value=100.0),
        ]
    )
    await test_session.commit()

    resp = await auth_client.get("/api/analytics/unit-cost")
    assert resp.status_code == 200
    data = resp.json()
    fx = data["fx_usd_brl"]
    expected_total = round((1.0 + 0.1) * fx, 2)
    assert data["has_cost_data"] is True
    assert data["totals"]["total_cost_brl"] == expected_total
    assert data["cost_per_conversation_brl"] == round(expected_total / 2, 2)
    assert data["cost_per_qualified_lead_brl"] == expected_total


# ─── baseline before/after ───


@pytest.mark.asyncio(loop_scope="function")
async def test_outcomes_baseline_compares_two_windows(auth_client, test_session, test_org):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    test_session.add_all(
        [
            # previous 30d window: 1 conversation
            Conversation(
                org_id=test_org.id,
                channel="whatsapp",
                created_at=now - timedelta(days=45),
            ),
            # current 30d window: 3 conversations
            *[
                Conversation(
                    org_id=test_org.id,
                    channel="whatsapp",
                    created_at=now - timedelta(days=2),
                )
                for _ in range(3)
            ],
        ]
    )
    await test_session.commit()

    resp = await auth_client.get("/api/analytics/outcomes?days=30&baseline_days=30")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enquiries"] == 3
    assert data["previous"]["enquiries"] == 1
    assert data["delta"]["enquiries"] == 2
    assert data["comparable"] is True
    assert data["window"]["days"] == 30


@pytest.mark.asyncio(loop_scope="function")
async def test_outcomes_marks_incomparable_without_baseline(auth_client, test_session, test_org):
    test_session.add(
        Conversation(
            org_id=test_org.id,
            channel="whatsapp",
            created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
        )
    )
    await test_session.commit()

    resp = await auth_client.get("/api/analytics/outcomes?days=30&baseline_days=30")
    assert resp.status_code == 200
    data = resp.json()
    assert data["previous"]["enquiries"] == 0
    assert data["comparable"] is False
