"""Billing is a commercial surface — fail-closed by default.

Default: billing_enabled=False, internal_mode=False. API router does not mount
billing; dashboard billing/proposal/trial return 404. No half-enabled
commercial flow exposed unless explicitly enabled.
"""

from aios.config import settings
from httpx import AsyncClient


class TestBillingDisabled:
    async def test_checkout_is_not_mounted(self, auth_client: AsyncClient):
        response = await auth_client.post(
            "/api/billing/create-checkout",
            json={"org_id": "test-org-id", "price_id": "price_test"},
        )
        assert response.status_code == 404

    async def test_portal_is_not_mounted(self, auth_client: AsyncClient):
        response = await auth_client.post(
            "/api/billing/create-portal", json={"org_id": "test-org-id"}
        )
        assert response.status_code == 404

    async def test_plans_endpoint_is_not_mounted(self, async_client: AsyncClient):
        response = await async_client.get("/api/billing/plans")
        assert response.status_code == 404

    async def test_usage_endpoint_is_not_mounted(self, auth_client: AsyncClient):
        response = await auth_client.get("/api/billing/usage")
        assert response.status_code == 404

    async def test_billing_page_not_exposed_by_default(self, auth_client: AsyncClient):
        response = await auth_client.get("/dashboard/billing", follow_redirects=False)
        assert response.status_code == 404

    async def test_proposal_not_exposed_by_default(self, auth_client: AsyncClient):
        response = await auth_client.get("/dashboard/proposal", follow_redirects=False)
        assert response.status_code == 404

    async def test_billing_trial_not_exposed_by_default(self, auth_client: AsyncClient):
        response = await auth_client.post("/dashboard/billing/trial", follow_redirects=False)
        assert response.status_code == 404


def test_billing_disabled_by_default():
    assert settings.billing_enabled is False
