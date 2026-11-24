"""Analytics KPI API: authoritative CRM metrics, deterministic interpretation."""

from datetime import datetime, timedelta, timezone

from aios.db.models import AuditLog, CrmDeal, PendingAction, User
from aios.api.auth import _create_access_token


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


async def test_kpi_catalog_endpoint_reports_levels_and_unknowns(auth_client):
    resp = await auth_client.get("/api/analytics/kpi/catalog")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "measurement_model" in body
    assert {"business", "department", "process", "agent_team", "infra_resource"} <= set(body["measurement_model"]["levels"])
    statuses = {m["status"] for m in body["metrics"]}
    assert "not_instrumented" in statuses
    assert body["measurement_model"]["principles"]


async def test_governance_kpis_are_org_scoped_and_no_fake(auth_client, test_db_session, test_org, second_org):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    test_db_session.add_all([
        AuditLog(org_id=test_org.id, action="x", resource_type="t"),
        AuditLog(org_id=second_org.id, action="y", resource_type="t"),
        PendingAction(org_id=test_org.id, agent_id="a1", conversation_id="c1", tool_name="t", status="approved", created_at=now - timedelta(hours=2), decided_at=now - timedelta(hours=1)),
        PendingAction(org_id=test_org.id, agent_id="a1", conversation_id="c1", tool_name="t", status="rejected", created_at=now - timedelta(hours=3), decided_at=now - timedelta(hours=2)),
        PendingAction(org_id=second_org.id, agent_id="a2", conversation_id="c2", tool_name="t", status="approved", created_at=now - timedelta(hours=1), decided_at=now),
    ])
    await test_db_session.commit()

    resp = await auth_client.get("/api/analytics/kpi/governance")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == "org"
    assert body["org_id"] == test_org.id
    by_key = {m["key"]: m for m in body["metrics"]}
    assert by_key["governance.audit_events"]["value"] == 1
    assert by_key["governance.approval_rejection_rate"]["value"] == 0.5
    assert body["guardrails"]["no_fake_metrics"] is True
    # missing/unknown sources must be explicit, not fabricated
    for key in ["security.incidents_open", "privacy.requests_open"]:
        assert by_key[key]["status"] in {"unknown", "partial"}
        assert by_key[key]["value"] is None or isinstance(by_key[key]["value"], (int, float))


async def test_target_validation_rejects_missing_baseline_and_evidence(auth_client):
    resp = await auth_client.post("/api/analytics/kpi/targets/validate", json={
        "metric_key": "crm.win_rate",
        "target_value": 0.9,
        "balancing_metrics": [],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["persistence"]["persisted"] is False
    assert body["persistence"]["mode"] == "org_extra_data"
    assert body["persistence"]["schema_table"] is None
    assert any("baseline" in e for e in body["errors"])
    assert any("evidence" in e for e in body["errors"])


async def test_kpi_target_set_and_list_persisted_in_org_extra_data(auth_client, test_db_session, test_org):
    payload = {
        "metric_key": "crm.win_rate",
        "target_value": 0.7,
        "baseline_value": 0.55,
        "baseline_window_days": 30,
        "evidence": "CRM export 2026-Q2",
        "owner": "sales-lead",
        "balancing_metrics": ["crm.close_rate", "crm.average_deal_size"],
    }
    resp = await auth_client.post("/api/analytics/kpi/targets", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["persistence"]["persisted"] is True
    assert body["persistence"]["mode"] == "org_extra_data"
    assert body["persistence"]["schema_table"] is None
    assert body["target"]["metric_key"] == "crm.win_rate"
    assert body["target"]["provenance"]["actor_org_id"] == test_org.id
    assert body["count"] == 1
    assert body["history_count"] == 1

    await test_db_session.refresh(test_org)
    store = (test_org.extra_data or {}).get("kpi_targets", {})
    assert store.get("persistence") == "org_extra_data"
    assert len(store.get("targets", [])) == 1
    hist = (test_org.extra_data or {}).get("kpi_target_history", [])
    assert len(hist) == 1

    listed = await auth_client.get("/api/analytics/kpi/targets")
    assert listed.status_code == 200, listed.text
    lb = listed.json()
    assert lb["persistence"] == "org_extra_data"
    assert lb["schema_table"] is None
    assert lb["count"] == 1
    assert lb["history_count"] == 1
    assert lb["targets"][0]["owner"] == "sales-lead"


async def test_kpi_target_set_fail_closed_no_persist(auth_client, test_db_session, test_org):
    bad = {
        "metric_key": "crm.win_rate",
        "target_value": 0.9,
        "baseline_value": None,
        "baseline_window_days": 30,
        "evidence": "",
        "owner": "",
        "balancing_metrics": [],
    }
    resp = await auth_client.post("/api/analytics/kpi/targets", json=bad)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["ok"] is False
    assert detail["persistence"]["persisted"] is False
    assert any("baseline" in e for e in detail["errors"])
    assert any("evidence" in e for e in detail["errors"])

    await test_db_session.refresh(test_org)
    assert "kpi_targets" not in (test_org.extra_data or {})

    listed = await auth_client.get("/api/analytics/kpi/targets")
    assert listed.status_code == 200
    assert listed.json()["count"] == 0


async def test_kpi_target_history_and_transition_endpoints(auth_client, test_db_session, test_org):
    payload = {
        "metric_key": "crm.win_rate",
        "target_value": 0.7,
        "baseline_value": 0.55,
        "baseline_window_days": 30,
        "evidence": "CRM export 2026-Q2",
        "owner": "sales-lead",
        "balancing_metrics": ["crm.close_rate", "crm.average_deal_size"],
    }
    create = await auth_client.post("/api/analytics/kpi/targets", json=payload)
    assert create.status_code == 200, create.text

    bad = await auth_client.post("/api/analytics/kpi/targets/transition", json={
        "metric_key": "crm.win_rate",
        "status": "retired",
        "evidence": "",
    })
    assert bad.status_code == 422, bad.text

    ok = await auth_client.post("/api/analytics/kpi/targets/transition", json={
        "metric_key": "crm.win_rate",
        "status": "review",
        "evidence": "weekly governance review",
    })
    assert ok.status_code == 200, ok.text
    assert ok.json()["target"]["status"] == "review"

    hist = await auth_client.get("/api/analytics/kpi/targets/history?metric_key=crm.win_rate")
    assert hist.status_code == 200, hist.text
    hb = hist.json()
    assert hb["count"] == 2
    assert hb["history"][0]["event"] == "status_transition"
    assert hb["history"][0]["to_status"] == "review"
    assert hb["schema_table"] is None


async def test_process_global_metrics_require_superadmin(async_client, test_db_session, test_org):
    member = User(org_id=test_org.id, email="member-kpi@test.io", role="member", hashed_password="x")
    owner = User(org_id=test_org.id, email="owner-kpi@test.io", role="owner", hashed_password="x")
    test_db_session.add_all([member, owner])
    await test_db_session.commit()
    await test_db_session.refresh(member)
    await test_db_session.refresh(owner)

    async_client.headers["Authorization"] = f"Bearer {_create_access_token(member.id, member.org_id)}"
    resp = await async_client.get("/api/analytics/metrics")
    assert resp.status_code == 403

    async_client.headers["Authorization"] = f"Bearer {_create_access_token(owner.id, owner.org_id)}"
    resp = await async_client.get("/api/analytics/metrics")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tenant_scoped"] is False
    assert body["scope"] == "process_global"


async def test_routing_stats_requires_superadmin(async_client, auth_headers, test_db_session, test_user):
    resp = await async_client.get("/api/analytics/routing")
    assert resp.status_code == 401

    async_client.headers.update(auth_headers)
    resp = await async_client.get("/api/analytics/routing")
    assert resp.status_code == 403

    test_user.role = "owner"
    await test_db_session.commit()
    resp = await async_client.get("/api/analytics/routing")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, dict)
    assert body["scope"] == "process_global"
    assert body["tenant_scoped"] is False
    assert body["caveats"]
    assert {"down_total", "hold_total", "up_total"} <= set(body["stats"])
