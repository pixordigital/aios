"""Billing is a commercial surface and AIOS ships as an internal tool first.

The router is deliberately not mounted, so these tests assert the surface is
absent rather than half-working. Re-enable together with multi-tenant onboarding.
"""

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

    async def test_billing_page_is_not_mounted(self, auth_client: AsyncClient):
        # The dashboard redirects unauthenticated HTML requests (303), so what
        # matters is that the page is not served.
        response = await auth_client.get("/dashboard/billing", follow_redirects=False)
        assert response.status_code != 200
