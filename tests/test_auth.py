"""Auth tests.

Self-service registration is disabled (internal tool), so accounts are created
directly in the test DB — the same way the operator provisions them.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from aios.api.auth import _hash_password
from aios.db.models import Organization, User


class TestAuth:
    """Auth endpoint tests."""

    async def test_login(self, async_client: AsyncClient, test_session: AsyncSession):
        """A provisioned account can log in."""
        org = Organization(name="Login Org", slug="login-org")
        test_session.add(org)
        await test_session.flush()
        user = User(
            email="login@example.com",
            hashed_password=_hash_password("LoginPass123"),
            org_id=org.id,
            role="admin",
        )
        test_session.add(user)
        await test_session.commit()

        response = await async_client.post(
            "/api/auth/login",
            json={"email": "login@example.com", "password": "LoginPass123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_login_invalid_password(
        self, async_client: AsyncClient, test_session: AsyncSession
    ):
        """Wrong password is rejected."""
        org = Organization(name="Wrong Pass Org", slug="wrong-pass-org")
        test_session.add(org)
        await test_session.flush()
        test_session.add(
            User(
                email="wrongpass@example.com",
                hashed_password=_hash_password("CorrectPass123"),
                org_id=org.id,
                role="admin",
            )
        )
        await test_session.commit()

        response = await async_client.post(
            "/api/auth/login",
            json={"email": "wrongpass@example.com", "password": "WrongPass123"},
        )
        assert response.status_code == 401

    async def test_refresh_token(self, async_client: AsyncClient, test_session: AsyncSession):
        """Refresh token round-trips into a new pair."""
        org = Organization(name="Refresh Org", slug="refresh-org")
        test_session.add(org)
        await test_session.flush()
        test_session.add(
            User(
                email="refresh@example.com",
                hashed_password=_hash_password("RefreshPass123"),
                org_id=org.id,
                role="admin",
            )
        )
        await test_session.commit()

        login = await async_client.post(
            "/api/auth/login",
            json={"email": "refresh@example.com", "password": "RefreshPass123"},
        )
        assert login.status_code == 200
        refresh_token = login.json()["refresh_token"]

        response = await async_client.post(
            "/api/auth/refresh", json={"refresh_token": refresh_token}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_refresh_token_invalid(self, async_client: AsyncClient):
        """Test invalid refresh token fails."""
        response = await async_client.post(
            "/api/auth/refresh", json={"refresh_token": "invalid.token.here"}
        )
        assert response.status_code == 401

    async def test_register_is_not_mounted(self, async_client: AsyncClient):
        """No self-service signup: the route does not exist in this build."""
        resp = await async_client.post(
            "/api/auth/register",
            json={"email": "newuser@example.com", "password": "SecurePass123", "org_name": "Test"},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_password_validation_helpers():
    """Password policy still rejects the obvious bad inputs."""
    from aios.api.auth import _validate_password
    from fastapi import HTTPException

    for bad in ("short", "password"):
        with pytest.raises(HTTPException):
            _validate_password(bad)
