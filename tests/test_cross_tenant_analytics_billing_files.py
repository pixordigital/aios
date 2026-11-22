"""Cross-tenant 404 mismatch metric coverage for analytics/billing/files."""

import pytest
from sqlalchemy import select

from aios.db.models import Agent, Artifact, Budget
from aios.governance.security import SecurityEvent


@pytest.mark.asyncio(loop_scope="function")
async def test_cross_tenant_telemetry_agent_records_metric(auth_client, test_db_session, second_org):
    other = Agent(org_id=second_org.id, name="Other Agent", status="active")
    test_db_session.add(other)
    await test_db_session.commit()
    await test_db_session.refresh(other)

    resp = await auth_client.get(f"/api/analytics/telemetry/agent/{other.id}")
    assert resp.status_code == 404, resp.text

    rows = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        )
    ).scalars().all()
    assert any(
        e.payload.get("metric") == "cross_tenant_block"
        and e.payload.get("resource_type") == "Agent"
        and e.payload.get("resource_org_id") == second_org.id
        and e.payload.get("agent_id") == other.id
        and e.source == "analytics.api.telemetry_agent"
        for e in rows
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_cross_tenant_file_read_records_metric(auth_client, test_db_session, second_org):
    other = Artifact(
        org_id=second_org.id,
        filename="secret.txt",
        content_type="text/plain",
        size_bytes=3,
        storage_path="/tmp/does-not-matter",
    )
    test_db_session.add(other)
    await test_db_session.commit()
    await test_db_session.refresh(other)

    resp = await auth_client.get(f"/api/files/{other.id}/read")
    assert resp.status_code == 404, resp.text

    rows = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        )
    ).scalars().all()
    assert any(
        e.payload.get("metric") == "cross_tenant_block"
        and e.payload.get("resource_type") == "Artifact"
        and e.payload.get("resource_org_id") == second_org.id
        and e.payload.get("artifact_id") == other.id
        and e.source == "files.api.read_file"
        for e in rows
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_cross_tenant_budget_mutations_record_metric(test_db_session, second_org, test_org, test_user):
    """Billing router not mounted; test handlers directly."""
    from types import SimpleNamespace
    from fastapi import HTTPException

    from aios.api.billing import delete_budget, patch_budget, update_budget

    other = Budget(org_id=second_org.id, name="Other", type="operation", amount_brl=100.0, period="monthly")
    test_db_session.add(other)
    await test_db_session.commit()
    await test_db_session.refresh(other)

    user = SimpleNamespace(id=test_user.id)

    with pytest.raises(HTTPException) as exc:
        await update_budget(
            other.id,
            SimpleNamespace(name="X", type="operation", amount_brl=10.0, period="monthly", scope={}, country="BR", block_on_exceed=True),
            db=test_db_session,
            org_id=test_org.id,
            user=user,
        )
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        await patch_budget(other.id, {"name": "X"}, db=test_db_session, org_id=test_org.id, user=user)
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        await delete_budget(other.id, db=test_db_session, org_id=test_org.id, user=user)
    assert exc.value.status_code == 404

    rows = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        )
    ).scalars().all()
    for source in ("billing.api.update_budget", "billing.api.patch_budget", "billing.api.delete_budget"):
        assert any(
            e.payload.get("metric") == "cross_tenant_block"
            and e.payload.get("resource_type") == "Budget"
            and e.payload.get("resource_org_id") == second_org.id
            and e.payload.get("budget_id") == other.id
            and e.source == source
            for e in rows
        ), source
