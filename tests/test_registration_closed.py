"""Self-service signup is a multi-tenant commercial surface, disabled by design.

AIOS ships as an internal tool: accounts are provisioned by the operator, so
both the API and dashboard registration routes are absent — not merely gated by
a flag that could be flipped.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_api_register_is_not_mounted(async_client: AsyncClient):
    r = await async_client.post(
        "/api/auth/register",
        json={"email": "closed@test.com", "password": "pass12345", "org_name": "ClosedOrg"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_dashboard_register_is_not_mounted(async_client: AsyncClient):
    r = await async_client.get("/dashboard/register")
    assert r.status_code == 404
    r2 = await async_client.post(
        "/dashboard/register",
        data={"name": "A", "email": "a@b.com", "password": "pass12345", "org_name": "Org"},
    )
    assert r2.status_code == 404
