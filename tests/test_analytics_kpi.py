"""Analytics KPI API: authoritative CRM metrics, deterministic interpretation."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from aios.db.models import AuditLog, CrmDeal, KpiTarget, KpiTargetEvent, PendingAction, User
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
    assert body["persistence"]["mode"] == "schema_tables"
    assert body["persistence"]["schema_table"] is None
    assert any("baseline" in e for e in body["errors"])
    assert any("evidence" in e for e in body["errors"])


async def test_kpi_target_set_and_list_persisted_in_schema_tables(auth_client, test_db_session, test_org):
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
    assert body["persistence"] == {
        "persisted": True,
        "mode": "schema_tables",
        "schema_table": "kpi_targets",
        "storage": "kpi_targets",
        "history_storage": "kpi_target_events",
    }
    assert body["target"]["metric_key"] == "crm.win_rate"
    assert body["target"]["provenance"]["actor_org_id"] == test_org.id
    assert body["count"] == 1
    assert body["history_count"] == 1

    rows = (await test_db_session.execute(
        select(KpiTarget).where(KpiTarget.org_id == test_org.id)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].metric_key == "crm.win_rate"
    assert rows[0].owner == "sales-lead"
    events = (await test_db_session.execute(
        select(KpiTargetEvent).where(KpiTargetEvent.org_id == test_org.id)
    )).scalars().all()
    assert len(events) == 1
    assert events[0].event == "target_created"
    assert events[0].target_id == rows[0].id
    assert events[0].actor_org_id == test_org.id
    assert events[0].at

    await test_db_session.refresh(test_org)
    assert (test_org.extra_data or {}) == {"plan": "pro"}

    listed = await auth_client.get("/api/analytics/kpi/targets")
    assert listed.status_code == 200, listed.text
    lb = listed.json()
    assert lb["persistence"] == {
        "persisted": True,
        "mode": "schema_tables",
        "schema_table": "kpi_targets",
        "storage": "kpi_targets",
        "history_storage": "kpi_target_events",
    }
    assert lb["schema_table"] == "kpi_targets"
    assert lb["storage"] == "kpi_targets"
    assert lb["history_storage"] == "kpi_target_events"
    assert lb["count"] == 1
    assert lb["history_count"] == 1
    assert lb["targets"][0]["owner"] == "sales-lead"
    assert lb["targets"][0]["id"] == rows[0].id


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
    assert detail["persistence"]["mode"] == "schema_tables"
    assert detail["persistence"]["schema_table"] == "kpi_targets"
    assert any("baseline" in e for e in detail["errors"])
    assert any("evidence" in e for e in detail["errors"])

    await test_db_session.refresh(test_org)
    assert (test_org.extra_data or {}) == {"plan": "pro"}
    assert (await test_db_session.execute(select(KpiTarget))).scalars().all() == []
    assert (await test_db_session.execute(select(KpiTargetEvent))).scalars().all() == []

    listed = await auth_client.get("/api/analytics/kpi/targets")
    assert listed.status_code == 200
    assert listed.json()["count"] == 0
    assert listed.json()["history_count"] == 0


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
    bad_detail = bad.json()["detail"]
    assert bad_detail["persistence"]["persisted"] is False
    assert bad_detail["persistence"]["mode"] == "schema_tables"
    assert bad_detail["persistence"]["schema_table"] == "kpi_targets"
    assert len((await test_db_session.execute(
        select(KpiTargetEvent).where(KpiTargetEvent.org_id == test_org.id)
    )).scalars().all()) == 1

    ok = await auth_client.post("/api/analytics/kpi/targets/transition", json={
        "metric_key": "crm.win_rate",
        "status": "review",
        "evidence": "weekly governance review",
    })
    assert ok.status_code == 200, ok.text
    ob = ok.json()
    assert ob["persistence"]["persisted"] is True
    assert ob["persistence"]["schema_table"] == "kpi_targets"
    assert ob["target"]["status"] == "review"
    assert ob["history_count"] == 2

    rows = (await test_db_session.execute(
        select(KpiTarget).where(KpiTarget.org_id == test_org.id)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "review"
    events = (await test_db_session.execute(
        select(KpiTargetEvent).where(KpiTargetEvent.org_id == test_org.id)
        .order_by(KpiTargetEvent.at.desc())
    )).scalars().all()
    assert len(events) == 2
    assert events[0].event == "status_transition"
    assert events[0].from_status == "active"
    assert events[0].to_status == "review"
    assert events[0].evidence == "weekly governance review"
    assert events[0].actor_org_id == test_org.id
    assert events[1].event == "target_created"

    hist = await auth_client.get("/api/analytics/kpi/targets/history?metric_key=crm.win_rate")
    assert hist.status_code == 200, hist.text
    hb = hist.json()
    assert hb["persistence"] == {
        "persisted": True,
        "mode": "schema_tables",
        "schema_table": "kpi_target_events",
        "storage": "kpi_target_events",
        "history_storage": "kpi_target_events",
    }
    assert hb["storage"] == "kpi_target_events"
    assert hb["schema_table"] == "kpi_target_events"
    assert hb["max_entries"] == 200
    assert hb["count"] == 2
    assert hb["history"][0]["event"] == "status_transition"
    assert hb["history"][0]["from_status"] == "active"
    assert hb["history"][0]["to_status"] == "review"
    assert hb["history"][1]["event"] == "target_created"


async def test_kpi_target_endpoints_are_org_scoped(auth_client, test_db_session, test_org, second_org):
    test_db_session.add_all([
        KpiTarget(
            org_id=second_org.id, metric_key="crm.win_rate", target_value=0.9,
            baseline_value=0.8, baseline_window_days=30, evidence="other org", owner="other",
        ),
    ])
    await test_db_session.flush()
    other_target = (await test_db_session.execute(
        select(KpiTarget).where(KpiTarget.org_id == second_org.id)
    )).scalars().one()
    test_db_session.add(KpiTargetEvent(
        org_id=second_org.id, target_id=other_target.id, event="target_created",
        metric_key="crm.win_rate", to_status="active", actor_org_id=second_org.id,
    ))
    await test_db_session.commit()

    listed = await auth_client.get("/api/analytics/kpi/targets")
    assert listed.status_code == 200, listed.text
    lb = listed.json()
    assert lb["count"] == 0
    assert lb["history_count"] == 0
    assert lb["targets"] == []

    hist = await auth_client.get("/api/analytics/kpi/targets/history")
    assert hist.status_code == 200, hist.text
    assert hist.json()["count"] == 0
    assert hist.json()["history"] == []

    # Writing the same metric in the authenticated org must not touch the other org row.
    created = await auth_client.post("/api/analytics/kpi/targets", json={
        "metric_key": "crm.win_rate",
        "target_value": 0.7,
        "baseline_value": 0.55,
        "baseline_window_days": 30,
        "evidence": "CRM export",
        "owner": "sales-lead",
        "balancing_metrics": ["crm.close_rate", "crm.average_deal_size"],
    })
    assert created.status_code == 200, created.text
    assert created.json()["count"] == 1
    assert created.json()["target"]["provenance"]["actor_org_id"] == test_org.id

    other_rows = (await test_db_session.execute(
        select(KpiTarget).where(KpiTarget.org_id == second_org.id)
    )).scalars().all()
    assert len(other_rows) == 1
    assert other_rows[0].id == other_target.id
    assert other_rows[0].evidence == "other org"
    other_events = (await test_db_session.execute(
        select(KpiTargetEvent).where(KpiTargetEvent.org_id == second_org.id)
    )).scalars().all()
    assert len(other_events) == 1
    assert other_events[0].actor_org_id == second_org.id


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
