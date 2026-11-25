"""Inbox tenant-scope tests."""


class TestInboxTenantScope:
    async def test_cross_tenant_conversation_access_records_metric(self, auth_client, test_db_session, second_org, test_user):
        from sqlalchemy import select

        from aios.db.models import Conversation
        from aios.governance.security import SecurityEvent

        other = Conversation(
            org_id=second_org.id,
            channel="web",
            external_id="ext-other-1",
            extra_data={"status": "open"},
        )
        test_db_session.add(other)
        await test_db_session.commit()
        await test_db_session.refresh(other)

        cases = [
            ("get", f"/api/inbox/{other.id}", None, "inbox.api.get_conversation"),
            ("post", f"/api/inbox/{other.id}/assign?assignee_id={test_user.id}", None, "inbox.api.assign"),
            ("post", f"/api/inbox/{other.id}/unassign", None, "inbox.api.unassign"),
            ("post", f"/api/inbox/{other.id}/close", None, "inbox.api.close"),
            ("post", f"/api/inbox/{other.id}/reopen", None, "inbox.api.reopen"),
            ("post", f"/api/inbox/{other.id}/send?content=hello", None, "inbox.api.send"),
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
                and e.payload.get("resource_type") == "Conversation"
                and e.payload.get("resource_org_id") == second_org.id
                and e.payload.get("conversation_id") == other.id
                and e.source == source
                for e in rows
            ), source

    async def test_cross_tenant_channel_and_assignee_refs_record_metric(self, auth_client, test_db_session, second_org, test_user):
        from sqlalchemy import select

        from aios.db.models import ChannelConnection, Conversation, User
        from aios.governance.security import SecurityEvent

        own_org_id = test_user.org_id
        other_user = User(email="other@example.com", hashed_password="x", org_id=second_org.id)
        other_channel = ChannelConnection(org_id=second_org.id, channel_type="web", config={}, label="Other")
        own_channel = ChannelConnection(org_id=own_org_id, channel_type="web", config={}, label="Own")
        test_db_session.add_all([other_user, other_channel, own_channel])
        await test_db_session.commit()
        for row in (other_user, other_channel, own_channel):
            await test_db_session.refresh(row)

        conv = Conversation(
            org_id=own_org_id, channel="web", external_id="ext-own-1",
            channel_connection_id=other_channel.id,
            extra_data={"assigned_to": other_user.id},
        )
        own_conv = Conversation(
            org_id=own_org_id, channel="web", external_id="ext-own-2",
            channel_connection_id=own_channel.id,
            extra_data={"assigned_to": test_user.id},
        )
        test_db_session.add_all([conv, own_conv])
        await test_db_session.commit()
        for row in (conv, own_conv):
            await test_db_session.refresh(row)

        # Mismatched refs keep the exact 200-with-nulled-refs / 400 responses.
        resp = await auth_client.get(f"/api/inbox/{conv.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["channel_label"] == "web" and body["assigned_to"] is None and body["assignee"] is None
        resp = await auth_client.post(f"/api/inbox/{conv.id}/assign?assignee_id={other_user.id}")
        assert resp.status_code == 400 and resp.json()["detail"] == "Invalid assignee"

        stmt = select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        rows = (await test_db_session.execute(stmt)).scalars().all()
        expected = [
            ("inbox.api.get_conversation.channel_mismatch", "ChannelConnection", "channel_id", other_channel.id),
            ("inbox.api.get_conversation.assignee_mismatch", "User", "user_id", other_user.id),
            ("inbox.api.assign.assignee_mismatch", "User", "user_id", other_user.id),
        ]
        for source, resource_type, key, resource_id in expected:
            assert any(
                e.org_id == own_org_id
                and e.source == source
                and e.payload.get("metric") == "cross_tenant_block"
                and e.payload.get("requested_org_id") == own_org_id
                and e.payload.get("resource_org_id") == second_org.id
                and e.payload.get("resource_type") == resource_type
                and e.payload.get(key) == resource_id
                for e in rows
            ), source

        # Same-org and missing refs stay silent.
        before = len(rows)
        resp = await auth_client.get(f"/api/inbox/{own_conv.id}")
        assert resp.status_code == 200
        resp = await auth_client.post(f"/api/inbox/{own_conv.id}/assign?assignee_id=missing-id")
        assert resp.status_code == 400
        after = (await test_db_session.execute(stmt)).scalars().all()
        assert len(after) == before
