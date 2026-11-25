"""Channel tests."""

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
        assert "items" in data
        assert isinstance(data["items"], list)
        assert len(data["items"]) >= 1

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

    async def test_test_channel_requires_auth(self, async_client: AsyncClient):
        """Unauthenticated channel test must be rejected."""
        response = await async_client.post(
            "/api/channels/test",
            json={"channel_type": "web", "config": {}},
        )
        assert response.status_code == 401

    async def test_test_channel_blocks_private_url(self, auth_client: AsyncClient):
        """Channel test with internal URL must be blocked (SSRF guard)."""
        response = await auth_client.post(
            "/api/channels/test",
            json={
                "channel_type": "evolution",
                "config": {"server_url": "http://169.254.169.254", "api_key": "x"},
            },
        )
        assert response.status_code == 200
        assert response.json()["ok"] is False


class TestChannelTenantScope:
    async def test_cross_tenant_channel_access_records_metric(self, auth_client, test_db_session, second_org):
        from sqlalchemy import select

        from aios.db.models import ChannelConnection
        from aios.governance.security import SecurityEvent

        other = ChannelConnection(
            org_id=second_org.id,
            channel_type="web",
            label="Other Org Channel",
            config={},
        )
        test_db_session.add(other)
        await test_db_session.commit()
        await test_db_session.refresh(other)

        cases = [
            ("get", f"/api/channels/{other.id}", None, "channels.api.get_channel"),
            ("put", f"/api/channels/{other.id}", {"label": "x"}, "channels.api.update_channel"),
            ("post", f"/api/channels/{other.id}/toggle", None, "channels.api.toggle_channel"),
            ("post", f"/api/channels/{other.id}/start", None, "channels.api.start_channel"),
            ("delete", f"/api/channels/{other.id}", None, "channels.api.delete_channel"),
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
                and e.payload.get("resource_type") == "ChannelConnection"
                and e.payload.get("resource_org_id") == second_org.id
                and e.payload.get("channel_id") == other.id
                and e.source == source
                for e in rows
            ), source

    async def test_cross_tenant_create_and_qrcode_refs_record_metric(self, auth_client, test_db_session, test_org, second_org):
        from sqlalchemy import select

        from aios.db.models import Agent, ChannelConnection, Team
        from aios.governance.security import SecurityEvent

        other_agent = Agent(name="Other Agent", org_id=second_org.id)
        other_team = Team(name="Other Team", org_id=second_org.id)
        other_channel = ChannelConnection(org_id=second_org.id, channel_type="evolution", config={}, label="Other")
        own_agent = Agent(name="Own Agent", org_id=test_org.id)
        test_db_session.add_all([other_agent, other_team, other_channel, own_agent])
        await test_db_session.commit()
        for row in (other_agent, other_team, other_channel, own_agent):
            await test_db_session.refresh(row)

        # Mismatched refs keep the exact 400 / ok:false responses.
        resp = await auth_client.post("/api/channels", json={
            "label": "x", "channel_type": "web", "config": {}, "agent_id": other_agent.id,
        })
        assert resp.status_code == 400 and resp.json()["detail"] == "agent_id inválido"
        resp = await auth_client.post("/api/channels", json={
            "label": "x", "channel_type": "web", "config": {}, "team_id": other_team.id,
        })
        assert resp.status_code == 400 and resp.json()["detail"] == "team_id inválido"
        resp = await auth_client.get(f"/api/channels/evolution/qrcode?channel_id={other_channel.id}&instance_name=x")
        assert resp.status_code == 200
        assert resp.json() == {"ok": False, "message": "Invalid Evolution channel"}

        stmt = select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        rows = (await test_db_session.execute(stmt)).scalars().all()
        expected = [
            ("channels.api.create_channel.agent_mismatch", "Agent", "agent_id", other_agent.id),
            ("channels.api.create_channel.team_mismatch", "Team", "team_id", other_team.id),
            ("channels.api.evolution_qrcode.channel_mismatch", "ChannelConnection", "channel_id", other_channel.id),
        ]
        for source, resource_type, key, resource_id in expected:
            assert any(
                e.org_id == test_org.id
                and e.source == source
                and e.payload.get("metric") == "cross_tenant_block"
                and e.payload.get("requested_org_id") == test_org.id
                and e.payload.get("resource_org_id") == second_org.id
                and e.payload.get("resource_type") == resource_type
                and e.payload.get(key) == resource_id
                for e in rows
            ), source

        # Same-org and missing refs stay silent.
        before = len(rows)
        resp = await auth_client.post("/api/channels", json={
            "label": "x", "channel_type": "web", "config": {}, "agent_id": own_agent.id,
        })
        assert resp.status_code == 200
        resp = await auth_client.post("/api/channels", json={
            "label": "x", "channel_type": "web", "config": {}, "agent_id": "missing-id",
        })
        assert resp.status_code == 400
        resp = await auth_client.get("/api/channels/evolution/qrcode?channel_id=missing-id&instance_name=x")
        assert resp.status_code == 200 and resp.json()["ok"] is False
        after = (await test_db_session.execute(stmt)).scalars().all()
        assert len(after) == before