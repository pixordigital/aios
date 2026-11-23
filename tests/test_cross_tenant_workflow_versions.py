"""Cross-tenant mismatch metric coverage for workflows/versions 404 paths."""

import pytest
from sqlalchemy import select

from aios.db.models import Agent, AgentVersion, Workflow, WorkflowRun
from aios.governance.security import SecurityEvent


def _metric_rows(rows, *, resource_type, resource_org_id, source):
    return [
        e
        for e in rows
        if e.payload.get("metric") == "cross_tenant_block"
        and e.payload.get("resource_type") == resource_type
        and e.payload.get("resource_org_id") == resource_org_id
        and e.source == source
    ]


@pytest.mark.asyncio(loop_scope="function")
async def test_cross_tenant_workflow_run_mismatch_records_metric(auth_client, test_db_session, test_org, second_org):
    wf1 = Workflow(org_id=test_org.id, name="wf1")
    wf2 = Workflow(org_id=second_org.id, name="wf2")
    test_db_session.add_all([wf1, wf2])
    await test_db_session.commit()
    await test_db_session.refresh(wf1)
    await test_db_session.refresh(wf2)

    run = WorkflowRun(workflow_id=wf1.id, org_id=test_org.id, status="done", inputs={}, outputs={}, node_status={})
    test_db_session.add(run)
    await test_db_session.commit()
    await test_db_session.refresh(run)

    # caller org1 owns run, but wf_id points to org2 workflow -> wf mismatch metric, 404
    resp = await auth_client.get(f"/api/workflows/{wf2.id}/runs/{run.id}")
    assert resp.status_code == 404, resp.text

    rows = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        )
    ).scalars().all()
    assert _metric_rows(rows, resource_type="Workflow", resource_org_id=second_org.id, source="workflows.api.get_run.workflow")


@pytest.mark.asyncio(loop_scope="function")
async def test_cross_tenant_workflow_resume_mismatch_records_metric(auth_client, test_db_session, test_org, second_org):
    wf1 = Workflow(org_id=test_org.id, name="wf1")
    wf2 = Workflow(org_id=second_org.id, name="wf2")
    test_db_session.add_all([wf1, wf2])
    await test_db_session.commit()
    await test_db_session.refresh(wf1)
    await test_db_session.refresh(wf2)

    run = WorkflowRun(workflow_id=wf1.id, org_id=test_org.id, status="failed", inputs={}, outputs={}, node_status={})
    test_db_session.add(run)
    await test_db_session.commit()
    await test_db_session.refresh(run)

    resp = await auth_client.post(f"/api/workflows/{wf2.id}/resume/{run.id}")
    assert resp.status_code == 404, resp.text

    rows = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        )
    ).scalars().all()
    assert _metric_rows(rows, resource_type="Workflow", resource_org_id=second_org.id, source="workflows.api.resume_run.workflow")


@pytest.mark.asyncio(loop_scope="function")
async def test_cross_tenant_version_diff_compare_records_metric(auth_client, test_db_session, test_org, second_org):
    a1 = Agent(org_id=test_org.id, name="A1", status="active")
    a2 = Agent(org_id=second_org.id, name="A2", status="active")
    test_db_session.add_all([a1, a2])
    await test_db_session.commit()
    await test_db_session.refresh(a1)
    await test_db_session.refresh(a2)

    v1 = AgentVersion(agent_id=a1.id, org_id=test_org.id, version=1, name="A1")
    v2 = AgentVersion(agent_id=a2.id, org_id=second_org.id, version=1, name="A2")
    test_db_session.add_all([v1, v2])
    await test_db_session.commit()
    await test_db_session.refresh(v1)
    await test_db_session.refresh(v2)

    resp = await auth_client.get(f"/api/agents/{a1.id}/versions/{v1.id}/diff?compare={v2.id}")
    assert resp.status_code == 404, resp.text

    rows = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        )
    ).scalars().all()
    assert _metric_rows(rows, resource_type="AgentVersion", resource_org_id=second_org.id, source="api.versions.diff_compare")


@pytest.mark.asyncio(loop_scope="function")
async def test_cross_tenant_version_get_records_metric(auth_client, test_db_session, test_org, second_org):
    a1 = Agent(org_id=test_org.id, name="A1", status="active")
    a2 = Agent(org_id=second_org.id, name="A2", status="active")
    test_db_session.add_all([a1, a2])
    await test_db_session.commit()
    await test_db_session.refresh(a1)
    await test_db_session.refresh(a2)

    v2 = AgentVersion(agent_id=a2.id, org_id=second_org.id, version=1, name="A2")
    test_db_session.add(v2)
    await test_db_session.commit()
    await test_db_session.refresh(v2)

    resp = await auth_client.get(f"/api/agents/{a1.id}/versions/{v2.id}")
    assert resp.status_code == 404, resp.text

    rows = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        )
    ).scalars().all()
    assert _metric_rows(rows, resource_type="AgentVersion", resource_org_id=second_org.id, source="api.versions.get")
