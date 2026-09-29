"""Team tests."""

import pytest
from httpx import AsyncClient


class TestTeamManagerRequired:
    """Every team must have a manager."""

    async def test_team_without_manager_rejected(self, auth_client: AsyncClient):
        """With agents in the org, creating a manager-less team must fail."""
        await auth_client.post(
            "/api/agents",
            json={"name": "Mgr Candidate", "agent_type": "manager"},
        )
        response = await auth_client.post(
            "/api/teams",
            json={"name": "No Manager Team", "routing_strategy": "supervisor"},
        )
        assert response.status_code == 422
        assert "manager" in response.json()["detail"].lower()

    async def test_team_with_manager_accepted(self, auth_client: AsyncClient):
        """Supplying a valid manager satisfies the rule."""
        agent = await auth_client.post(
            "/api/agents",
            json={"name": "Real Manager", "agent_type": "manager"},
        )
        mgr_id = agent.json()["id"]
        response = await auth_client.post(
            "/api/teams",
            json={
                "name": "Managed Team",
                "routing_strategy": "supervisor",
                "manager_agent_id": mgr_id,
            },
        )
        assert response.status_code == 200

    async def test_manager_from_other_org_rejected(self, auth_client: AsyncClient):
        """A manager id that does not exist must not be accepted."""
        response = await auth_client.post(
            "/api/teams",
            json={
                "name": "Bad Manager Team",
                "routing_strategy": "supervisor",
                "manager_agent_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert response.status_code == 422


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
        assert "items" in data
        assert isinstance(data["items"], list)
        assert len(data["items"]) >= 1

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
        # Create agents — one of them is the team manager (required rule)
        agent1 = await auth_client.post(
            "/api/agents",
            json={"name": "Agent 1", "agent_type": "manager"}
        )
        agent2 = await auth_client.post(
            "/api/agents",
            json={"name": "Agent 2", "agent_type": "custom"}
        )
        agent_ids = [agent1.json()["id"], agent2.json()["id"]]

        # Create team
        team_resp = await auth_client.post(
            "/api/teams",
            json={
                "name": "Agent Team",
                "routing_strategy": "supervisor",
                "manager_agent_id": agent1.json()["id"],
            }
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