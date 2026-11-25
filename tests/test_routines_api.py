import pytest


@pytest.mark.asyncio
async def test_routines_list_returns_200_and_known_fixed_tick(auth_client):
    resp = await auth_client.get("/api/routines")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list)
    ids = {r["routine_id"] for r in data}
    assert "fixed_tick:backup_tick" in ids
    hb = next(r for r in data if r["routine_id"] == "fixed_tick:backup_tick")
    assert hb["source_type"] == "fixed_tick"
    assert hb["schedule_kind"] == "daily_fixed"
    assert "next_run_at" in hb or hb.get("next_run_at") is None


@pytest.mark.asyncio
async def test_routines_detail_404_for_missing(auth_client):
    resp = await auth_client.get("/api/routines/fixed_tick:does-not-exist")
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_routines_detail_path_id(auth_client):
    resp = await auth_client.get("/api/routines/fixed_tick:backup_tick")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["routine_id"] == "fixed_tick:backup_tick"
    assert data["name"]


@pytest.mark.asyncio
async def test_routines_org_scoping(auth_client, test_db_session, second_org):
    from aios.db.models import AutomationTrigger, Workflow

    wf = Workflow(org_id=second_org.id, name="other-org-wf", description="", timeout_seconds=30)
    test_db_session.add(wf)
    await test_db_session.flush()
    trig = AutomationTrigger(
        workflow_id=wf.id,
        org_id=second_org.id,
        type="cron",
        name="other-org-cron",
        config={},
        cron_expr="0 9 * * *",
        is_active=True,
    )
    test_db_session.add(trig)
    await test_db_session.commit()

    resp = await auth_client.get("/api/routines")
    assert resp.status_code == 200, resp.text
    ids = {r["routine_id"] for r in resp.json()}
    assert f"automation_cron:{trig.id}" not in ids
