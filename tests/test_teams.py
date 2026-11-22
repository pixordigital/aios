"""Team tests."""

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


class TestTeamTenantScope:
    async def test_cross_tenant_team_access_records_metric(self, auth_client, test_db_session, second_org):
        from sqlalchemy import select

        from aios.db.models import Team
        from aios.governance.security import SecurityEvent

        other = Team(org_id=second_org.id, name="Other Org Team", routing_strategy="supervisor")
        test_db_session.add(other)
        await test_db_session.commit()
        await test_db_session.refresh(other)

        cases = [
            ("get", f"/api/teams/{other.id}", None, "teams.api.get_team"),
            ("delete", f"/api/teams/{other.id}", None, "teams.api.delete_team"),
            ("post", f"/api/teams/{other.id}/agents", {"agent_ids": ["00000000-0000-0000-0000-000000000001"]}, "teams.api.assign_agents"),
        ]
        for method, path, body, source in cases:
            req = getattr(auth_client, method)
            resp = await req(path, json=body) if body is not None else await req(path)
            assert resp.status_code == 404, (path, resp.text)

        rows = (
            await test_db_session.execute(
                select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
            )
        ).scalars().all()
        for _, _, _, source in cases:
            assert any(
                e.payload.get("metric") == "cross_tenant_block"
                and e.payload.get("resource_type") == "Team"
                and e.payload.get("resource_org_id") == second_org.id
                and e.payload.get("team_id") == other.id
                and e.source == source
                for e in rows
            ), source