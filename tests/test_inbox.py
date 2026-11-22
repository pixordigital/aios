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
