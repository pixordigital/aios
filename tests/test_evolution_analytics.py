"""Tests for Evolution analytics endpoint."""

import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from aios.db.models import ChannelConnection, Conversation, Message, Organization, User


@pytest.mark.asyncio
async def test_evolution_analytics_basic(test_db_session, test_org, test_user, auth_client):
    """Test evolution analytics endpoint returns correct stats."""
    # Create channel connection for evolution
    chan = ChannelConnection(
        org_id=test_org.id,
        channel_type="evolution",
        label="WhatsApp Test",
        config={"instance": "test-instance", "server_url": "http://evolution:8080", "api_key": "test-key"},
        is_active=True,
    )
    test_db_session.add(chan)
    await test_db_session.commit()
    await test_db_session.refresh(chan)

    # Create conversation linked to channel
    conv = Conversation(
        org_id=test_org.id,
        channel_connection_id=chan.id,
        channel="evolution",
        external_id="test-conv-1",
    )
    test_db_session.add(conv)
    await test_db_session.commit()
    await test_db_session.refresh(conv)

    # Add messages
    for i in range(5):
        msg = Message(
            org_id=test_org.id,
            conversation_id=conv.id,
            role="user" if i % 2 == 0 else "assistant",
            content=f"Message {i}",
        )
        test_db_session.add(msg)
    await test_db_session.commit()

    # Call analytics endpoint
    response = await auth_client.get(f"/api/channels/evolution/test-instance/analytics?days=7")
    assert response.status_code == 200
    data = response.json()
    
    assert data["instance_name"] == "test-instance"
    assert data["channel_connection_id"] == chan.id
    assert data["total_messages"] == 5
    assert data["inbound"] == 3  # user messages
    assert data["outbound"] == 2  # assistant messages
    assert len(data["daily"]) == 1
    assert data["daily"][0]["total"] == 5


@pytest.mark.asyncio
async def test_evolution_analytics_not_found(test_db_session, test_org, test_user, auth_client):
    """Test evolution analytics returns 404 for unknown instance."""
    response = await auth_client.get("/api/channels/evolution/unknown-instance/analytics?days=7")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert data["detail"] == "Instance not found or not linked to this org"


@pytest.mark.asyncio
async def test_evolution_analytics_daily_breakdown(test_db_session, test_org, test_user, auth_client):
    """Test evolution analytics daily breakdown works correctly."""
    chan = ChannelConnection(
        org_id=test_org.id,
        channel_type="evolution",
        label="WhatsApp Test",
        config={"instance": "analytics-instance", "server_url": "http://evolution:8080", "api_key": "test-key"},
        is_active=True,
    )
    test_db_session.add(chan)
    await test_db_session.commit()
    await test_db_session.refresh(chan)

    # Create conversations on different days
    from datetime import timedelta
    base_date = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    
    for day_offset in range(3):
        conv = Conversation(
            org_id=test_org.id,
            channel_connection_id=chan.id,
            channel="evolution",
            external_id=f"conv-day-{day_offset}",
            created_at=base_date - timedelta(days=day_offset),
        )
        test_db_session.add(conv)
        await test_db_session.commit()
        await test_db_session.refresh(conv)
        
        # Add messages for this day
        for i in range(2):
            msg = Message(
                org_id=test_org.id,
                conversation_id=conv.id,
                role="user" if i == 0 else "assistant",
                content=f"Day {day_offset} msg {i}",
            )
            test_db_session.add(msg)
    await test_db_session.commit()

    response = await auth_client.get("/api/channels/evolution/analytics-instance/analytics?days=7")
    assert response.status_code == 200
    data = response.json()
    
    assert data["total_messages"] == 6
    assert len(data["daily"]) == 3
    # Each day should have 2 messages (1 inbound, 1 outbound)
    for day_stat in data["daily"]:
        assert day_stat["total"] == 2
        assert day_stat["inbound"] == 1
        assert day_stat["outbound"] == 1


@pytest.mark.asyncio
async def test_evolution_analytics_isolation_by_org(test_db_session, test_user, auth_client):
    """Test evolution analytics only returns data for the user's org."""
    from aios.db.models import Organization
    
    # Create second org
    org2 = Organization(name="Org 2", slug="org-2", extra_data={"plan": "pro"})
    test_db_session.add(org2)
    await test_db_session.commit()
    await test_db_session.refresh(org2)
    
    # Create user in org2
    user2 = User(
        email="test2@example.com",
        hashed_password="hashed",
        org_id=org2.id,
        role="admin",
    )
    test_db_session.add(user2)
    await test_db_session.commit()
    await test_db_session.refresh(user2)

    # Create channel in org2
    chan = ChannelConnection(
        org_id=org2.id,
        channel_type="evolution",
        label="WhatsApp Org2",
        config={"instance": "shared-instance", "server_url": "http://evolution:8080", "api_key": "test-key"},
        is_active=True,
    )
    test_db_session.add(chan)
    await test_db_session.commit()
    await test_db_session.refresh(chan)

    # Create conversation and messages in org2
    conv = Conversation(
        org_id=org2.id,
        channel_connection_id=chan.id,
        channel="evolution",
        external_id="org2-conv",
    )
    test_db_session.add(conv)
    await test_db_session.commit()
    await test_db_session.refresh(conv)
    
    msg = Message(org_id=org2.id, conversation_id=conv.id, role="user", content="Org2 msg")
    test_db_session.add(msg)
    await test_db_session.commit()

    # Try to access org2's instance from test_user's org (test_org)
    # Should not find it because channel belongs to different org
    response = await auth_client.get("/api/channels/evolution/shared-instance/analytics?days=7")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert data["detail"] == "Instance not found or not linked to this org"