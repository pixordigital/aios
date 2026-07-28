"""Team tests."""

import pytest
from httpx import AsyncClient


class TestTeams:
    """Team CRUD tests."""

    async def test_create_team(self, auth_client: AsyncClient):
        """Test team creation."""
        response = await auth_client.post(
            "/api/teams",
            json={
                "name": "Test Team",
                "routing_strategy": "supervisor",
                "agent_ids": []
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Team"
        assert data["routing_strategy"] == "supervisor"
        assert "id" in data

    async def test_list_teams(self, auth_client: AsyncClient):
        """Test listing teams."""
        await auth_client.post(
            "/api/teams",
            json={"name": "List Team", "routing_strategy": "round_robin"}
        )
        response = await auth_client.get("/api/teams")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    async def test_get_team(self, auth_client: AsyncClient):
        """Test getting a single team."""
        create_resp = await auth_client.post(
            "/api/teams",
            json={"name": "Get Team", "routing_strategy": "broadcast"}
        )
        team_id = create_resp.json()["id"]

        response = await auth_client.get(f"/api/teams/{team_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == team_id

    async def test_delete_team(self, auth_client: AsyncClient):
        """Test deleting a team."""
        create_resp = await auth_client.post(
            "/api/teams",
            json={"name": "To Delete", "routing_strategy": "supervisor"}
        )
        team_id = create_resp.json()["id"]

        response = await auth_client.delete(f"/api/teams/{team_id}")
        assert response.status_code == 200
        assert response.json()["ok"] is True

        get_resp = await auth_client.get(f"/api/teams/{team_id}")
        assert get_resp.status_code == 404

    async def test_assign_agents_to_team(self, auth_client: AsyncClient):
        """Test assigning agents to team."""
        # Create agents
        agent1 = await auth_client.post(
            "/api/agents",
            json={"name": "Agent 1", "agent_type": "custom"}
        )
        agent2 = await auth_client.post(
            "/api/agents",
            json={"name": "Agent 2", "agent_type": "custom"}
        )
        agent_ids = [agent1.json()["id"], agent2.json()["id"]]

        # Create team
        team_resp = await auth_client.post(
            "/api/teams",
            json={"name": "Agent Team", "routing_strategy": "supervisor"}
        )
        team_id = team_resp.json()["id"]

        # Assign agents
        response = await auth_client.post(
            f"/api/teams/{team_id}/agents",
            json={"agent_ids": agent_ids}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["agents"]) == 2