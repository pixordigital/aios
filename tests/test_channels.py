"""Channel tests."""

import pytest
from httpx import AsyncClient


class TestChannels:
    """Channel CRUD and management tests."""

    async def test_create_channel(self, auth_client: AsyncClient):
        """Test creating a channel."""
        response = await auth_client.post(
            "/api/channels",
            json={
                "label": "Test Channel",
                "channel_type": "web",
                "config": {"platform": "WebSocket"}
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["label"] == "Test Channel"
        assert data["channel_type"] == "web"
        assert "id" in data

    async def test_list_channels(self, auth_client: AsyncClient):
        """Test listing channels."""
        await auth_client.post(
            "/api/channels",
            json={"label": "List Channel", "channel_type": "web", "config": {}}
        )
        response = await auth_client.get("/api/channels")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    async def test_get_channel(self, auth_client: AsyncClient):
        """Test getting a single channel."""
        create_resp = await auth_client.post(
            "/api/channels",
            json={"label": "Get Channel", "channel_type": "web", "config": {}}
        )
        channel_id = create_resp.json()["id"]

        response = await auth_client.get(f"/api/channels/{channel_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == channel_id

    async def test_update_channel(self, auth_client: AsyncClient):
        """Test updating a channel."""
        create_resp = await auth_client.post(
            "/api/channels",
            json={"label": "Original", "channel_type": "web", "config": {}}
        )
        channel_id = create_resp.json()["id"]

        response = await auth_client.put(
            f"/api/channels/{channel_id}",
            json={"label": "Updated", "is_active": False}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["label"] == "Updated"
        assert data["is_active"] is False

    async def test_delete_channel(self, auth_client: AsyncClient):
        """Test deleting a channel."""
        create_resp = await auth_client.post(
            "/api/channels",
            json={"label": "To Delete", "channel_type": "web", "config": {}}
        )
        channel_id = create_resp.json()["id"]

        response = await auth_client.delete(f"/api/channels/{channel_id}")
        assert response.status_code == 200
        assert response.json()["ok"] is True

        get_resp = await auth_client.get(f"/api/channels/{channel_id}")
        assert get_resp.status_code == 404

    async def test_toggle_channel(self, auth_client: AsyncClient):
        """Test toggling channel active status."""
        create_resp = await auth_client.post(
            "/api/channels",
            json={"label": "Toggle Test", "channel_type": "web", "config": {}}
        )
        channel_id = create_resp.json()["id"]

        # Initially active
        get_resp = await auth_client.get(f"/api/channels/{channel_id}")
        assert get_resp.json()["is_active"] is True

        # Toggle off
        response = await auth_client.post(f"/api/channels/{channel_id}/toggle")
        assert response.status_code == 200
        assert response.json()["is_active"] is False

        # Toggle on
        response = await auth_client.post(f"/api/channels/{channel_id}/toggle")
        assert response.status_code == 200
        assert response.json()["is_active"] is True

    async def test_test_channel(self, auth_client: AsyncClient):
        """Test channel connection without saving."""
        response = await auth_client.post(
            "/api/channels/test",
            json={
                "channel_type": "web",
                "config": {"platform": "WebSocket"}
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "ok" in data