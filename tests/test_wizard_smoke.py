"""Smoke: POST /dashboard/agents/save 422 validations + f328da5 org_id fix."""

import pytest
from httpx import AsyncClient
import jwt
from datetime import datetime, timedelta, timezone
from aios.config import settings
from aios.db.models import Organization

REF = {"referer": "http://test/dashboard/agents/new"}


def _cookie_for(user):
    tok = jwt.encode(
        {"sub": user.id, "org": user.org_id, "type": "access",
         "iat": datetime.now(timezone.utc),
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )
    return tok


@pytest.mark.asyncio(loop_scope="function")
async def test_wizard_invalid_agent_type_422(async_client: AsyncClient, test_session, test_org, test_user):
    tok = _cookie_for(test_user)
    async_client.cookies.set("aios_token", tok)
    r = await async_client.post("/dashboard/agents/save", headers=REF, data={
        "name": "X", "agent_type": "bad_type", "system_prompt": "hello",
        "model": "openai/gpt-4o-mini", "temperature": "0.7", "max_tokens": "4096", "tools": ""
    })
    assert r.status_code == 422
    assert "inv" in r.text.lower()


@pytest.mark.asyncio(loop_scope="function")
async def test_wizard_invalid_temperature_422(async_client: AsyncClient, test_session, test_org, test_user):
    tok = _cookie_for(test_user)
    async_client.cookies.set("aios_token", tok)
    r = await async_client.post("/dashboard/agents/save", headers=REF, data={
        "name": "X", "agent_type": "custom", "system_prompt": "hi",
        "model": "openai/gpt-4o", "temperature": "5", "max_tokens": "4096", "tools": ""
    })
    assert r.status_code == 422


@pytest.mark.asyncio(loop_scope="function")
async def test_wizard_invalid_max_tokens_422(async_client: AsyncClient, test_session, test_org, test_user):
    tok = _cookie_for(test_user)
    async_client.cookies.set("aios_token", tok)
    r = await async_client.post("/dashboard/agents/save", headers=REF, data={
        "name": "X", "agent_type": "custom", "system_prompt": "hi",
        "model": "openai/gpt-4o", "temperature": "0.7", "max_tokens": "10", "tools": ""
    })
    assert r.status_code == 422


@pytest.mark.asyncio(loop_scope="function")
async def test_wizard_invalid_tools_422(async_client: AsyncClient, test_session, test_org, test_user):
    tok = _cookie_for(test_user)
    async_client.cookies.set("aios_token", tok)
    r = await async_client.post("/dashboard/agents/save", headers=REF, data={
        "name": "X", "agent_type": "custom", "system_prompt": "hi",
        "model": "openai/gpt-4o", "temperature": "0.7", "max_tokens": "4096", "tools": "tool_inexistente_xyz"
    })
    assert r.status_code == 422
    assert "tool" in r.text.lower()


@pytest.mark.asyncio(loop_scope="function")
async def test_wizard_org_id_fix_303(async_client: AsyncClient, test_session, test_org, test_user):
    """f328da5: org_id NameError must not 500 — valid create 303."""
    tok = _cookie_for(test_user)
    async_client.cookies.set("aios_token", tok)
    r = await async_client.post("/dashboard/agents/save", headers=REF, data={
        "name": "Smoke OK", "agent_type": "custom", "system_prompt": "system smoke ok",
        "model": "openai/gpt-4o-mini", "temperature": "0.7", "max_tokens": "1024", "tools": ""
    }, follow_redirects=False)
    assert r.status_code == 303
    # persisted
    from sqlalchemy import select
    from aios.db.models import Agent
    rows = (await test_session.execute(select(Agent).where(Agent.org_id == test_org.id))).scalars().all()
    assert any(a.name == "Smoke OK" for a in rows)


@pytest.mark.asyncio(loop_scope="function")
async def test_wizard_saves_hitl_discount_threshold(async_client: AsyncClient, test_session, test_org, test_user):
    """agent_save read request.form.get(...) directly, but Starlette's
    request.form is a coroutine -- every valid save raised AttributeError and
    500'd, so the discount threshold never reached governance_config at all."""
    async_client.cookies.set("aios_token", _cookie_for(test_user))
    r = await async_client.post("/dashboard/agents/save", headers=REF, data={
        "name": "Smoke Threshold", "agent_type": "custom", "system_prompt": "hi",
        "model": "openai/gpt-4o-mini", "temperature": "0.7", "max_tokens": "1024",
        "tools": "", "hitl_discount_threshold": "25",
    }, follow_redirects=False)
    assert r.status_code == 303
    from sqlalchemy import select
    from aios.db.models import Agent
    agent = (await test_session.execute(
        select(Agent).where(Agent.name == "Smoke Threshold"))).scalars().first()
    assert agent is not None
    assert agent.governance_config["hitl_discount_threshold"] == 25


@pytest.mark.asyncio(loop_scope="function")
async def test_wizard_clamps_hitl_discount_threshold(async_client: AsyncClient, test_session, test_org, test_user):
    async_client.cookies.set("aios_token", _cookie_for(test_user))
    await async_client.post("/dashboard/agents/save", headers=REF, data={
        "name": "Smoke Clamp", "agent_type": "custom", "system_prompt": "hi",
        "model": "openai/gpt-4o-mini", "temperature": "0.7", "max_tokens": "1024",
        "tools": "", "hitl_discount_threshold": "999",
    }, follow_redirects=False)
    from sqlalchemy import select
    from aios.db.models import Agent
    agent = (await test_session.execute(
        select(Agent).where(Agent.name == "Smoke Clamp"))).scalars().first()
    assert agent.governance_config["hitl_discount_threshold"] == 100
