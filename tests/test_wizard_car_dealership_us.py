"""Dashboard wizard/seed flow: car_dealership_us creates bound ICM agents."""

import pytest
from httpx import AsyncClient
import jwt
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from aios.config import settings
from aios.db.models import Agent

REF = {"referer": "http://test/dashboard/agents/new"}


def _cookie_for(user):
    return jwt.encode(
        {
            "sub": user.id,
            "org": user.org_id,
            "type": "access",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_agent_save_seeds_car_dealership_us_lead_capture_binding(
    async_client: AsyncClient, test_session, test_org, test_user
):
    async_client.cookies.set("aios_token", _cookie_for(test_user))
    r = await async_client.post(
        "/dashboard/agents/save",
        headers=REF,
        data={
            "name": "CD US Capture",
            "agent_type": "car_dealership_us_lead_capture",
            "system_prompt": "",
            "model": "openai/gpt-4o-mini",
            "temperature": "0.3",
            "max_tokens": "2048",
            "tools": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    agent = (
        await test_session.execute(select(Agent).where(Agent.name == "CD US Capture"))
    ).scalars().first()
    assert agent is not None
    assert agent.agent_type == "car_dealership_us_lead_capture"
    assert agent.extra_data["workflow_class"] == "car_dealership_us_lead_capture"
    assert agent.extra_data["workflow_registry"] == "aios.verticals.car_dealership_us.workflows"
    assert agent.extra_data["icm"] == {
        "workspace_id": "cd_us_ops",
        "stage_id": "car_dealership_us_lead_capture",
    }
    profile = agent.extra_data["car_dealership_us_profile"]
    assert profile["business_name"]
    assert profile["services"]
    assert profile["hours"]
    assert profile["escalation_rules"]
    # Template defaults applied when fields left empty/default-ish.
    assert "rag_search" in agent.tools
    assert "notify_human" in agent.tools


@pytest.mark.asyncio(loop_scope="function")
async def test_agent_save_seeds_car_dealership_us_follow_up_binding(
    async_client: AsyncClient, test_session, test_org, test_user
):
    async_client.cookies.set("aios_token", _cookie_for(test_user))
    r = await async_client.post(
        "/dashboard/agents/save",
        headers=REF,
        data={
            "name": "CD US Follow Up",
            "agent_type": "car_dealership_us_lead_follow_up",
            "system_prompt": "",
            "model": "openai/gpt-4o-mini",
            "temperature": "0.2",
            "max_tokens": "1024",
            "tools": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    agent = (
        await test_session.execute(select(Agent).where(Agent.name == "CD US Follow Up"))
    ).scalars().first()
    assert agent is not None
    assert agent.extra_data["workflow_class"] == "car_dealership_us_lead_follow_up"
    assert agent.extra_data["icm"]["stage_id"] == "car_dealership_us_lead_follow_up"
    assert "send_whatsapp" in agent.tools
    assert "crm_update_deal" in agent.tools


@pytest.mark.asyncio(loop_scope="function")
async def test_wizard_create_seeds_car_dealership_us_binding(
    async_client: AsyncClient, test_session, test_org, test_user, monkeypatch
):
    async_client.cookies.set("aios_token", _cookie_for(test_user))

    async def _fake_create_instance(name):
        return {"ok": True}

    monkeypatch.setattr("aios.core.evolution_api.evo_create_instance", _fake_create_instance)

    r = await async_client.post(
        "/dashboard/wizard/create",
        headers={"referer": "http://test/dashboard/wizard"},
        data={"phone": "15551234567", "vertical": "car_dealership_us_lead_capture"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard/evolution"

    agent = (
        await test_session.execute(
            select(Agent).where(Agent.agent_type == "car_dealership_us_lead_capture")
        )
    ).scalars().first()
    assert agent is not None
    assert agent.extra_data["workflow_class"] == "car_dealership_us_lead_capture"
    assert agent.extra_data["icm"]["stage_id"] == "car_dealership_us_lead_capture"
    assert agent.extra_data["car_dealership_us_profile"]["business_name"] == "Example Motors (US)"