"""Agent tests."""

import pytest
from httpx import AsyncClient


class TestAgents:
    """Agent CRUD tests."""

    async def test_create_agent(self, auth_client: AsyncClient):
        """Test agent creation."""
        response = await auth_client.post(
            "/api/agents",
            json={
                "name": "Test Agent",
                "agent_type": "custom",
                "system_prompt": "You are a helpful assistant",
                "llm_config": {
                    "model": "openai/gpt-4o-mini",
                    "temperature": 0.7,
                    "max_tokens": 4096
                },
                "tools": ["web_search"],
                "memory_config": {
                    "short_term": {"max_messages": 50},
                    "long_term": {"enabled": True, "top_k": 5},
                    "episodic": {"enabled": True, "summarize_after": 10}
                }
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Agent"
        assert data["agent_type"] == "custom"
        assert "id" in data

    async def test_list_agents(self, auth_client: AsyncClient):
        """Test listing agents."""
        # Create an agent first
        await auth_client.post(
            "/api/agents",
            json={
                "name": "List Test Agent",
                "agent_type": "custom",
                "system_prompt": "Test"
            }
        )
        response = await auth_client.get("/api/agents")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    async def test_get_agent(self, auth_client: AsyncClient):
        """Test getting a single agent."""
        # Create agent
        create_resp = await auth_client.post(
            "/api/agents",
            json={"name": "Get Test", "agent_type": "custom"}
        )
        agent_id = create_resp.json()["id"]

        response = await auth_client.get(f"/api/agents/{agent_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == agent_id
        assert data["name"] == "Get Test"

    async def test_update_agent(self, auth_client: AsyncClient):
        """Test updating an agent."""
        create_resp = await auth_client.post(
            "/api/agents",
            json={"name": "Original", "agent_type": "custom"}
        )
        agent_id = create_resp.json()["id"]

        response = await auth_client.put(
            f"/api/agents/{agent_id}",
            json={"name": "Updated Name", "llm_config": {"temperature": 0.5}}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"
        assert data["llm_config"]["temperature"] == 0.5

    async def test_delete_agent(self, auth_client: AsyncClient):
        """Test deleting an agent."""
        create_resp = await auth_client.post(
            "/api/agents",
            json={"name": "To Delete", "agent_type": "custom"}
        )
        agent_id = create_resp.json()["id"]

        response = await auth_client.delete(f"/api/agents/{agent_id}")
        assert response.status_code == 200
        assert response.json()["ok"] is True

        # Verify deleted
        get_resp = await auth_client.get(f"/api/agents/{agent_id}")
        assert get_resp.status_code == 404

    async def test_deploy_agent(self, auth_client: AsyncClient):
        """Test deploying an agent."""
        create_resp = await auth_client.post(
            "/api/agents",
            json={"name": "Deploy Test", "agent_type": "custom"}
        )
        agent_id = create_resp.json()["id"]

        response = await auth_client.post(f"/api/agents/{agent_id}/deploy")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "active"

    async def test_stop_agent(self, auth_client: AsyncClient):
        """Test stopping an agent."""
        create_resp = await auth_client.post(
            "/api/agents",
            json={"name": "Stop Test", "agent_type": "custom"}
        )
        agent_id = create_resp.json()["id"]

        # Deploy first
        await auth_client.post(f"/api/agents/{agent_id}/deploy")

        # Stop
        response = await auth_client.post(f"/api/agents/{agent_id}/stop")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "draft"

    async def test_unauthorized_access(self, async_client: AsyncClient):
        """Test that unauthenticated requests fail."""
        response = await async_client.get("/api/agents")
        assert response.status_code == 401