"""Analytics KPI API: authoritative CRM metrics, deterministic interpretation."""

from datetime import datetime, timedelta, timezone

from aios.db.models import CrmDeal


async def test_sales_kpis_use_deterministic_crm_data(auth_client, test_db_session, test_org):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    old = now - timedelta(days=40)
    rows = [
        CrmDeal(org_id=test_org.id, lead_name="A", stage="closed_won", value=100.0, created_at=old),
        CrmDeal(org_id=test_org.id, lead_name="B", stage="closed_lost", value=50.0, created_at=old),
        CrmDeal(org_id=test_org.id, lead_name="C", stage="closed_won", value=300.0, created_at=now),
        CrmDeal(org_id=test_org.id, lead_name="D", stage="prospection", value=20.0, created_at=now),
    ]
    test_db_session.add_all(rows)
    await test_db_session.commit()

    resp = await auth_client.get("/api/analytics/kpi/sales?baseline_days=30")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current"] == {
        "win_rate": 0.6667,
        "close_rate": 0.75,
        "average_deal_size": 200.0,
        "pipeline_deals": 4.0,
    }
    assert body["previous"]["win_rate"] == 0.5
    interp = body["interpretation"]
    assert "win_rate: 0.6667 (up 0.1667 vs baseline)" in interp["items"]
    assert interp["watch"] == "close_rate"
    assert "target" not in interp["summary"].lower()


async def test_sales_kpis_pipeline_filter_and_empty(auth_client, test_db_session, test_org):
    test_db_session.add(
        CrmDeal(org_id=test_org.id, lead_name="X", stage="closed_won", value=50.0, pipeline="p1")
    )
    await test_db_session.commit()

    resp = await auth_client.get("/api/analytics/kpi/sales?pipeline=p1")
    assert resp.status_code == 200
    assert resp.json()["current"]["pipeline_deals"] == 1.0
    assert resp.json()["current"]["win_rate"] == 1.0

    resp = await auth_client.get("/api/analytics/kpi/sales?pipeline=missing")
    assert resp.status_code == 200
    assert resp.json()["current"]["pipeline_deals"] == 0.0
    assert resp.json()["interpretation"]["watch"] is None
