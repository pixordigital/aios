"""Agent type tests - verify all agent types are functional."""

import pytest
from httpx import AsyncClient


AGENT_TYPES = [
    "custom",
    "orchestrator",
    "manager",
    "sdr",
    "closer",
    "support",
    "data_analyst",
    "data_scientist",
]


class TestAgentTypes:
    """Test each agent type can be created and deployed."""

    @pytest.mark.parametrize("agent_type", AGENT_TYPES)
    async def test_create_agent_type(self, auth_client: AsyncClient, agent_type: str):
        """Test creating each agent type."""
        response = await auth_client.post(
            "/api/agents",
            json={
                "name": f"Test {agent_type.title()} Agent",
                "agent_type": agent_type,
                "system_prompt": f"You are a {agent_type} agent",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["agent_type"] == agent_type
        assert "id" in data

    @pytest.mark.parametrize("agent_type", AGENT_TYPES)
    async def test_deploy_agent_type(self, auth_client: AsyncClient, agent_type: str):
        """Test deploying each agent type."""
        create_resp = await auth_client.post(
            "/api/agents",
            json={
                "name": f"Deploy {agent_type.title()} Agent",
                "agent_type": agent_type,
                "system_prompt": f"You are a {agent_type} agent",
            },
        )
        agent_id = create_resp.json()["id"]

        response = await auth_client.post(f"/api/agents/{agent_id}/deploy")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "active"

    @pytest.mark.parametrize("agent_type", AGENT_TYPES)
    async def test_agent_type_has_template(self, auth_client: AsyncClient, agent_type: str):
        """Test each agent type gets template defaults (except custom which is blank)."""
        response = await auth_client.post(
            "/api/agents",
            json={
                "name": f"Template {agent_type.title()} Agent",
                "agent_type": agent_type,
            },
        )
        assert response.status_code == 200
        data = response.json()
        # custom type has no template (blank by design), others should have prompts
        if agent_type != "custom":
            assert data["system_prompt"] != ""
        # All types should have tools list (even if empty)
        assert isinstance(data["tools"], list)

    @pytest.mark.parametrize("agent_type", AGENT_TYPES)
    async def test_agent_type_message_flow(self, auth_client: AsyncClient, agent_type: str):
        """Test full message flow with each agent type."""
        # Create agent
        create_resp = await auth_client.post(
            "/api/agents",
            json={
                "name": f"Flow {agent_type.title()} Agent",
                "agent_type": agent_type,
                "system_prompt": f"You are a {agent_type} agent. Reply briefly.",
            },
        )
        agent_id = create_resp.json()["id"]

        # Create conversation
        conv_resp = await auth_client.post(
            "/api/conversations",
            json={"channel": "web", "agent_id": agent_id},
        )
        conv_id = conv_resp.json()["id"]

        # Send message
        msg_resp = await auth_client.post(
            f"/api/conversations/{conv_id}/messages",
            json={"content": "Hello, this is a test message"},
        )
        assert msg_resp.status_code == 200
        data = msg_resp.json()
        assert "user_message" in data
        assert "reply" in data

    @pytest.mark.parametrize("agent_type", AGENT_TYPES)
    async def test_agent_type_with_tools(self, auth_client: AsyncClient, agent_type: str):
        """Test each agent type with tool configuration."""
        response = await auth_client.post(
            "/api/agents",
            json={
                "name": f"Tools {agent_type.title()} Agent",
                "agent_type": agent_type,
                "tools": ["web_search", "calculator", "current_datetime"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "web_search" in data["tools"]
        assert "calculator" in data["tools"]
        assert "current_datetime" in data["tools"]


class TestAgentQuotas:
    """Test agent quota enforcement per plan."""

    async def test_free_plan_max_agents(self, async_client: AsyncClient, test_db_session):
        """Free plan should allow max 2 agents."""
        # Create free org
        from aios.db.models import Organization, User
        from aios.api.auth import _hash_password
        import jwt
        from datetime import datetime, timedelta, timezone

        free_org = Organization(
            name="Free Org",
            slug="free-org",
            extra_data={"plan": "free"}
        )
        test_db_session.add(free_org)
        await test_db_session.commit()
        await test_db_session.refresh(free_org)

        free_user = User(
            email="free@example.com",
            hashed_password=_hash_password("testpass123"),
            org_id=free_org.id,
            role="admin"
        )
        test_db_session.add(free_user)
        await test_db_session.commit()
        await test_db_session.refresh(free_user)

        token = jwt.encode(
            {
                "sub": free_user.id,
                "org": free_user.org_id,
                "type": "access",
                "iat": datetime.now(timezone.utc),
                "exp": datetime.now(timezone.utc) + timedelta(minutes=60)
            },
            "test-secret",
            algorithm="HS256"
        )
        headers = {"Authorization": f"Bearer {token}"}
        async_client.headers.update(headers)

        # Create 2 agents
        for i in range(2):
            resp = await async_client.post(
                "/api/agents",
                json={"name": f"Free Agent {i}", "agent_type": "custom"},
            )
            assert resp.status_code == 200

        # 3rd should fail
        resp = await async_client.post(
            "/api/agents",
            json={"name": "Free Agent 3", "agent_type": "custom"},
        )
        assert resp.status_code == 403
        assert "quota" in resp.json()["detail"].lower()

    async def test_pro_plan_max_agents(self, async_client: AsyncClient):
        """Pro plan should allow more agents."""
        # Create pro org user
        from aios.db.models import Organization, User
        from aios.api.auth import _hash_password
        from sqlalchemy.ext.asyncio import AsyncSession

        # This test would need a pro org - skip for now
        pass


class TestAgentValidation:
    """Test agent input validation."""

    async def test_invalid_agent_type_rejected(self, auth_client: AsyncClient):
        """Invalid agent type should be rejected."""
        response = await auth_client.post(
            "/api/agents",
            json={
                "name": "Invalid Agent",
                "agent_type": "invalid_type",
            },
        )
        assert response.status_code == 422

    async def test_invalid_temperature_rejected(self, auth_client: AsyncClient):
        """Temperature outside 0-2 should be rejected."""
        response = await auth_client.post(
            "/api/agents",
            json={
                "name": "Invalid Temp Agent",
                "agent_type": "custom",
                "llm_config": {"temperature": 3.0},
            },
        )
        assert response.status_code == 422

    async def test_invalid_max_tokens_rejected(self, auth_client: AsyncClient):
        """Max tokens outside 256-16384 should be rejected."""
        response = await auth_client.post(
            "/api/agents",
            json={
                "name": "Invalid Tokens Agent",
                "agent_type": "custom",
                "llm_config": {"max_tokens": 100},
            },
        )
        assert response.status_code == 422

    async def test_invalid_tool_rejected(self, auth_client: AsyncClient):
        """Invalid tool should be rejected."""
        response = await auth_client.post(
            "/api/agents",
            json={
                "name": "Invalid Tool Agent",
                "agent_type": "custom",
                "tools": ["nonexistent_tool"],
            },
        )
        assert response.status_code == 422