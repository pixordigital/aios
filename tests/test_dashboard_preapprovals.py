"""Dashboard view of stored preapprovals: read-only and founder-scoped."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from aios.config import settings
from aios.db.models import User


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


_STORAGE_TEXT = "org.extra_data.security_policy (shared app DB; not independent/append-only storage)"


@pytest.mark.asyncio(loop_scope="function")
async def test_founder_sees_stored_values_and_no_write_route(
    async_client, test_session, test_org, test_user
):
    test_org.extra_data = {
        "founder_user_id": test_user.id,
        "security_policy": {
            "preapproved_actions": ["send_email"],
            "approvals": [{"id": "TICKET-42", "action": "http_request", "approved": True}],
            "updated_at": "2026-01-02T03:04:05",
            "updated_by": test_user.id,
        },
    }
    await test_session.commit()
    async_client.cookies.set("aios_token", _cookie_for(test_user))

    from aios.dashboard.app import router

    methods = {
        method
        for route in router.routes
        if route.path == "/dashboard/security/preapprovals"
        for method in route.methods
    }
    assert methods == {"GET"}

    page = await async_client.get("/dashboard/security/preapprovals")
    assert page.status_code == 200
    assert "send_email" in page.text
    assert "TICKET-42" in page.text
    assert "http_request" in page.text
    assert "2026-01-02T03:04:05" in page.text
    assert test_user.id in page.text
    assert _STORAGE_TEXT in page.text
    assert 'action="/dashboard/security/preapprovals"' not in page.text

    post = await async_client.post(
        "/dashboard/security/preapprovals",
        headers={"referer": "http://test/dashboard/security/preapprovals"},
    )
    assert post.status_code == 405


@pytest.mark.asyncio(loop_scope="function")
async def test_non_founder_denied(async_client, test_session, test_org, test_user):
    test_org.extra_data = {
        "security_policy": {"preapproved_actions": ["SECRET-NONFOUNDER"]}
    }
    await test_session.commit()
    async_client.cookies.set("aios_token", _cookie_for(test_user))

    page = await async_client.get("/dashboard/security/preapprovals")
    assert page.status_code == 403
    assert "SECRET-NONFOUNDER" not in page.text


@pytest.mark.asyncio(loop_scope="function")
async def test_cross_org_denied(
    async_client, test_session, test_org, second_org, test_user
):
    test_org.extra_data = {
        "founder_user_id": test_user.id,
        "security_policy": {"preapproved_actions": ["SECRET-OTHER-ORG"]},
    }
    cross_user = User(
        email="cross@example.com",
        hashed_password="x",
        org_id=second_org.id,
        role="admin",
    )
    test_session.add(cross_user)
    await test_session.commit()
    async_client.cookies.set("aios_token", _cookie_for(cross_user))
    async_client.cookies.set("aios_impersonate_org", test_org.id)

    page = await async_client.get("/dashboard/security/preapprovals")
    assert page.status_code == 403
    assert "SECRET-OTHER-ORG" not in page.text
