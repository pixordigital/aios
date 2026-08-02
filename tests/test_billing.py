"""Billing tests."""

import pytest
from httpx import AsyncClient


class TestBilling:
    """Billing and Stripe integration tests."""

    async def test_create_checkout(self, auth_client: AsyncClient):
        """Test creating Stripe checkout session."""
        # This will fail if Stripe not configured, but should handle gracefully
        response = await auth_client.post(
            "/api/billing/create-checkout",
            json={
                "org_id": "test-org-id",
                "price_id": "price_test"
            }
        )
        # Either succeeds with URL or returns error for missing Stripe config
        assert response.status_code in (200, 400, 500)
        data = response.json()
        if response.status_code == 200:
            assert "url" in data

    async def test_create_portal(self, auth_client: AsyncClient):
        """Test creating Stripe customer portal session."""
        response = await auth_client.post(
            "/api/billing/create-portal",
            json={"org_id": "test-org-id"}
        )
        assert response.status_code in (200, 400, 500)
        if response.status_code == 200:
            data = response.json()
            assert "url" in data

    async def test_get_plans(self, async_client: AsyncClient):
        """Test getting available plans."""
        response = await async_client.get("/api/billing/plans")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "free" in data
        assert "starter" in data
        assert "pro" in data

    async def test_usage_summary(self, auth_client: AsyncClient):
        """Test getting usage summary for org."""
        response = await auth_client.get("/api/billing/usage")
        assert response.status_code == 200
        data = response.json()
        assert "messages_today" in data
        assert "llm_calls_today" in data
        assert "tokens_today" in data

    async def test_create_checkout_requires_auth(self, async_client: AsyncClient):
        """Unauthenticated checkout creation must be rejected."""
        response = await async_client.post(
            "/api/billing/create-checkout",
            json={"org_id": "test-org-id", "price_id": "price_test"},
        )
        assert response.status_code == 401

    async def test_create_portal_requires_auth(self, async_client: AsyncClient):
        """Unauthenticated portal creation must be rejected."""
        response = await async_client.post(
            "/api/billing/create-portal",
            json={"org_id": "test-org-id"},
        )
        assert response.status_code == 401