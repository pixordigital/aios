"""Auth tests."""

import pytest
from httpx import AsyncClient


class TestAuth:
    """Auth endpoint tests."""

    async def test_register(self, async_client: AsyncClient):
        """Test user registration."""
        response = await async_client.post(
            "/api/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "SecurePass123",
                "org_name": "Test Org"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_register_duplicate_email(self, async_client: AsyncClient):
        """Test registering with existing email fails."""
        await async_client.post(
            "/api/auth/register",
            json={
                "email": "dup@example.com",
                "password": "Pass123",
                "org_name": "Org 1"
            }
        )
        response = await async_client.post(
            "/api/auth/register",
            json={
                "email": "dup@example.com",
                "password": "Pass123",
                "org_name": "Org 2"
            }
        )
        assert response.status_code == 409

    async def test_login(self, async_client: AsyncClient, auth_client: AsyncClient):
        """Test user login."""
        # Get credentials from auth_client fixture
        # Since auth_client is already logged in, we need to get the test user's email
        # For now, we test with a fresh login
        register_resp = await async_client.post(
            "/api/auth/register",
            json={
                "email": "login@example.com",
                "password": "LoginPass123",
                "org_name": "Login Org"
            }
        )
        assert register_resp.status_code == 200

        # Now login
        response = await async_client.post(
            "/api/auth/login",
            json={"email": "login@example.com", "password": "LoginPass123"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_login_invalid_password(self, async_client: AsyncClient):
        """Test login with wrong password fails."""
        await async_client.post(
            "/api/auth/register",
            json={
                "email": "wrongpass@example.com",
                "password": "CorrectPass123",
                "org_name": "Wrong Pass Org"
            }
        )
        response = await async_client.post(
            "/api/auth/login",
            json={"email": "wrongpass@example.com", "password": "WrongPass123"}
        )
        assert response.status_code == 401

    async def test_refresh_token(self, async_client: AsyncClient):
        """Test refresh token endpoint."""
        register_resp = await async_client.post(
            "/api/auth/register",
            json={
                "email": "refresh@example.com",
                "password": "RefreshPass123",
                "org_name": "Refresh Org"
            }
        )
        assert register_resp.status_code == 200
        refresh_token = register_resp.json()["refresh_token"]

        response = await async_client.post(
            "/api/auth/refresh",
            json={"refresh_token": refresh_token}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    async def test_refresh_token_invalid(self, async_client: AsyncClient):
        """Test invalid refresh token fails."""
        response = await async_client.post(
            "/api/auth/refresh",
            json={"refresh_token": "invalid.token.here"}
        )
        assert response.status_code == 401

    async def test_password_validation(self, async_client: AsyncClient):
        """Test password validation on register."""
        # Too short
        resp = await async_client.post(
            "/api/auth/register",
            json={"email": "short@example.com", "password": "short", "org_name": "Short"}
        )
        assert resp.status_code == 422

        # Common password
        resp = await async_client.post(
            "/api/auth/register",
            json={"email": "common@example.com", "password": "password", "org_name": "Common"}
        )
        assert resp.status_code == 422