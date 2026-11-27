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
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from aios.config import settings
from aios.core.agent import AgentRuntime
from aios.db.engine import async_session
from aios.db.models import (
    Agent,
    AgentPack,
    AgentPackVersion,
    Conversation,
    CrmDeal,
    PendingAction,
    UsageRecord,
    User,
)
from aios.icm.contracts import manifest_fingerprint
from aios.icm.dedupe_model import ICMSideEffect
from aios.verticals.car_dealership_us.workflows import LEAD_CAPTURE


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
        "name": "cd-us-lead-capture",
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
    agent = _agent(extra_data={"workflow_class": "unknown_paid_workflow"})
    with pytest.raises(Exception) as exc:
        AgentRuntime(agent)
    assert "not owned by any vertical contract" in str(exc.value)


def test_paid_workflow_without_icm_binding_refuses():
    agent = _agent(extra_data={"workflow_class": "car_dealership_us_lead_capture"})
    with pytest.raises(Exception) as exc:
        AgentRuntime(agent)
    assert "requires extra_data['icm']" in str(exc.value)


@pytest.mark.asyncio(loop_scope="function")
async def test_paid_workflow_binds_contract_and_restricts_tools(
    test_db_session, auth_client, test_org, test_user
):
    from aios.api.auth import _hash_password

    approver = User(
        email="paid-approver@example.com",
        hashed_password=_hash_password("testpass123"),
        org_id=test_org.id,
        role="admin",
    )
    pack = AgentPack(
        org_id=test_org.id,
        pack_key="paid-approval",
        name="Paid approval",
        created_by=test_user.id,
    )
    test_db_session.add_all([approver, pack])
    await test_db_session.flush()
    version = AgentPackVersion(
        pack_id=pack.id,
        org_id=test_org.id,
        version_semver="1.0.0",
        manifest_json={},
        capability_loss_json=[],
        provenance_json={},
        created_by=test_user.id,
    )
    test_db_session.add(version)
    await test_db_session.flush()
    approver_id, pack_id, version_id = approver.id, pack.id, version.id
    await test_db_session.commit()

    resp = await auth_client.post(
        f"/api/agent-packs/{pack_id}/activate", json={"version_id": version_id}
    )
    assert resp.status_code == 200, resp.text
    action_id = resp.json()["approval_action"]["id"]

    # POST created the real pending row; bind it to a trusted tool identity
    # before the second same-org human decides it.
    row = await test_db_session.get(PendingAction, action_id)
    assert row.org_id == test_org.id
    assert row.status == "pending"
    row.tool_name = "agent_run"
    await test_db_session.commit()

    import jwt

    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": approver_id,
            "org": test_org.id,
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=60),
        },
        "test-secret",
        algorithm="HS256",
    )
    resp = await auth_client.post(
        f"/api/approvals/{action_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    async with async_session() as sess:
        approved = await sess.get(PendingAction, action_id)
    assert approved.status == "approved"
    assert approved.org_id == test_org.id
    assert approved.decided_by == approver_id
    assert approved.tool_name == "agent_run"

    sync_engine = create_engine(settings.database_url.replace("sqlite+aiosqlite", "sqlite", 1))
    sync_session = None
    try:
        ICMSideEffect.__table__.create(sync_engine, checkfirst=True)
        sync_session = Session(sync_engine)
        agent = _agent(
            org_id=test_org.id,
            extra_data={
                "workflow_class": "car_dealership_us_lead_capture",
                "icm": {
                    "stage_id": "car_dealership_us_lead_capture",
                    "stage_manifest": LEAD_CAPTURE.model_dump(),
                    "icm_db_session": sync_session,
                    "preapproved": {
                        "approved": True,
                        "approval_id": approved.id,
                        "approved_fingerprint": manifest_fingerprint(LEAD_CAPTURE),
                        "actions": ["agent_run"],
                    },
                },
            },
        )
        runtime = AgentRuntime(agent)

        assert runtime.stage is not None
        assert runtime.stage.manifest.id == "car_dealership_us_lead_capture"
        assert runtime.stage.approval_bound is not None
        assert runtime.stage.approval_bound["approval_id"] == approved.id
        # Denylist from the contract is enforced on top of the agent's own policy.
        assert "execute_code" in runtime._denied_tools
        # Allowlist is intersected: only tools both the agent and the contract allow.
        # "__all__" means the contract allowlist becomes the whole policy; the
        # agent's own `tools` list only narrows what the ToolEngine exposes.
        assert runtime._allowed_tools == set(LEAD_CAPTURE.allowed_tools)
        assert runtime._stage_timeout == LEAD_CAPTURE.timeout_seconds
    finally:
        if sync_session is not None:
            sync_session.close()
        sync_engine.dispose()


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


# ─── dashboard approval authority ───


@pytest.mark.asyncio(loop_scope="function")
async def test_dashboard_member_cannot_approve(auth_client, test_session, test_org, test_user):
    from aios.api.auth import _hash_password

    member = User(
        email="member-approver@example.com",
        hashed_password=_hash_password("testpass123"),
        org_id=test_org.id,
        role="member",
    )
    test_session.add(member)
    await test_session.commit()

    action = PendingAction(
        org_id=test_org.id,
        agent_id="agent-paid-1",
        conversation_id="conv-1",
        tool_name="notify_human",
        tool_args={"reason": "clinically sensitive"},
    )
    test_session.add(action)
    await test_session.commit()
    action_id = action.id

    async with _cookie(auth_client, member):
        resp = await auth_client.post(
            f"/dashboard/approvals/{action_id}/approve",
            headers={"referer": "http://test/dashboard/approvals"},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    async with async_session() as sess:
        row = await sess.get(PendingAction, action_id)
    assert row.status == "pending"
    assert row.decided_by is None


@pytest.mark.asyncio(loop_scope="function")
async def test_dashboard_self_approval_blocked(auth_client, test_session, test_org, test_user):
    action = PendingAction(
        org_id=test_org.id,
        agent_id="agent-paid-1",
        conversation_id="conv-1",
        tool_name="notify_human",
        tool_args={"requested_by": test_user.id},
        status="pending",
    )
    test_session.add(action)
    await test_session.commit()
    action_id = action.id

    async with _cookie(auth_client, test_user):
        resp = await auth_client.post(
            f"/dashboard/approvals/{action_id}/approve",
            headers={"referer": "http://test/dashboard/approvals"},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    async with async_session() as sess:
        row = await sess.get(PendingAction, action_id)
    assert row.status == "pending"
    assert row.decided_by is None


@pytest.mark.asyncio(loop_scope="function")
async def test_dashboard_founder_approve_still_allowed(auth_client, test_session, test_org, test_user):
    test_user.role = "owner"
    test_org.extra_data = {**(test_org.extra_data or {}), "founder_user_id": test_user.id}
    await test_session.commit()

    action = PendingAction(
        org_id=test_org.id,
        agent_id="agent-paid-1",
        conversation_id="conv-1",
        tool_name="notify_human",
        tool_args={"reason": "clinically sensitive"},
        status="pending",
    )
    test_session.add(action)
    await test_session.commit()
    action_id = action.id

    async with _cookie(auth_client, test_user):
        resp = await auth_client.post(
            f"/dashboard/approvals/{action_id}/approve",
            headers={"referer": "http://test/dashboard/approvals"},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    async with async_session() as sess:
        row = await sess.get(PendingAction, action_id)
    assert row.status == "approved"
    assert row.decided_by == test_user.id


# ─── contract viewer ───


@pytest.mark.asyncio(loop_scope="function")
async def test_contracts_page_shows_contract_and_governed_agent(
    auth_client, test_session, test_org, test_user
):
    test_org.slug = "showcar"
    test_session.add(
        Agent(
            name="pet-lead-capture",
            org_id=test_org.id,
            extra_data={
                "workflow_class": "car_dealership_us_lead_capture",
                "icm": {"stage_id": "car_dealership_us_lead_capture"},
            },
        )
    )
    await test_session.commit()

    async with _cookie(auth_client, test_user):
        page = await auth_client.get("/dashboard/contracts")
    assert page.status_code == 200
    assert "car_dealership_us_lead_capture" in page.text
    assert "car_dealership_us_lead_follow_up" in page.text
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
