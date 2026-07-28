"""Conversation tests."""

import pytest
from httpx import AsyncClient


class TestConversations:
    """Conversation CRUD and messaging tests."""

    async def test_create_conversation(self, auth_client: AsyncClient):
        """Test creating a conversation."""
        response = await auth_client.post(
            "/api/conversations",
            json={"channel": "web", "agent_id": None, "team_id": None}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["channel"] == "web"
        assert "id" in data

    async def test_list_conversations(self, auth_client: AsyncClient):
        """Test listing conversations."""
        await auth_client.post(
            "/api/conversations",
            json={"channel": "web"}
        )
        response = await auth_client.get("/api/conversations")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    async def test_get_conversation(self, auth_client: AsyncClient):
        """Test getting a single conversation."""
        create_resp = await auth_client.post(
            "/api/conversations",
            json={"channel": "web"}
        )
        conv_id = create_resp.json()["id"]

        response = await auth_client.get(f"/api/conversations/{conv_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == conv_id

    async def test_send_message(self, auth_client: AsyncClient):
        """Test sending a message."""
        create_resp = await auth_client.post(
            "/api/conversations",
            json={"channel": "web"}
        )
        conv_id = create_resp.json()["id"]

        response = await auth_client.post(
            f"/api/conversations/{conv_id}/messages",
            json={"content": "Hello, world!"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "user_message" in data
        assert data["user_message"]["content"] == "Hello, world!"

    async def test_get_messages(self, auth_client: AsyncClient):
        """Test getting conversation messages."""
        create_resp = await auth_client.post(
            "/api/conversations",
            json={"channel": "web"}
        )
        conv_id = create_resp.json()["id"]

        # Send a few messages
        await auth_client.post(
            f"/api/conversations/{conv_id}/messages",
            json={"content": "Message 1"}
        )
        await auth_client.post(
            f"/api/conversations/{conv_id}/messages",
            json={"content": "Message 2"}
        )

        response = await auth_client.get(f"/api/conversations/{conv_id}/messages")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 2

    async def test_message_pagination(self, auth_client: AsyncClient):
        """Test message pagination."""
        create_resp = await auth_client.post(
            "/api/conversations",
            json={"channel": "web"}
        )
        conv_id = create_resp.json()["id"]

        # Send multiple messages
        for i in range(5):
            await auth_client.post(
                f"/api/conversations/{conv_id}/messages",
                json={"content": f"Message {i}"}
            )

        response = await auth_client.get(
            f"/api/conversations/{conv_id}/messages",
            params={"limit": 2, "before": None}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2