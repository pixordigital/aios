"""Capability registry API: tenant scope + deterministic solution-fit dispositions."""

from aios.db.models import Organization
from aios.governance.capability_registry import Capability

_HIGH = {
    "problem_fit": 0.9,
    "feasibility": 0.9,
    "commercial_viability": 0.9,
    "buying_readiness": 0.9,
    "evidence_confidence": 0.9,
}


async def test_create_list_and_evaluate(auth_client):
    resp = await auth_client.post(
        "/api/capabilities",
        json={
            "capability_key": "dealership-lead-ops",
            "name": "Dealership lead operations",
            "maturity": "production",
            "supported_use_cases": ["lead_qualification"],
            "deployment_evidence": ["pilot-1"],
            "is_commercially_available": True,
            "owner_id": "owner-1",
            "review_status": "approved",
        },
    )
    assert resp.status_code == 200, resp.text
    cap = resp.json()
    assert cap["maturity"] == "production"
    assert cap["is_commercially_available"] is True
    assert cap["owner_id"] == "owner-1"
    assert cap["review_status"] == "approved"

    listed = await auth_client.get("/api/capabilities")
    assert any(c["id"] == cap["id"] for c in listed.json()["items"])

    fit = await auth_client.post(
        "/api/capabilities/evaluate",
        json={
            "capability_id": cap["id"],
            "subject_id": "acct-1",
            "required_use_case": "lead_qualification",
            **_HIGH,
        },
    )
    assert fit.status_code == 200, fit.text
    body = fit.json()
    assert body["disposition"] == "qualified"
    assert body["capability_fit"] >= 0.9
    assert body["engineering_work_allowed"] is True

    assessments = await auth_client.get("/api/capabilities/assessments")
    assert any(a["id"] == body["id"] for a in assessments.json()["items"])


async def test_blueprint_is_read_only_and_uses_real_plan_limits(auth_client):
    from aios.config import DEFAULT_PLAN, PLANS

    resp = await auth_client.post(
        "/api/capabilities/blueprint",
        json={"agent_type": "support", "required_use_case": "support", **_HIGH},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["read_only"] is True and body["estimate"] is False
    assert body["disposition"] == "research_required"  # no capability recorded
    assert body["blueprint"]["agent_type"] == "support"
    assert body["blueprint"]["tools"]
    plan = PLANS.get(body["plan"], PLANS[DEFAULT_PLAN])
    for key, value in body["plan_limits"].items():
        assert value == plan.get(key), key
    assert body["limit_source"] == "aios/config.py:PLANS"
    assert body["enforced_by"] == "aios/core/limits.py:check_org_limits"

    bad = await auth_client.post("/api/capabilities/blueprint", json={"problem_fit": 2.0})
    assert bad.status_code == 400
    bad_type = await auth_client.post("/api/capabilities/blueprint", json={"agent_type": "nope"})
    assert bad_type.status_code == 400


async def test_fit_gates_contact_legal_and_maturity(auth_client):
    resp = await auth_client.post(
        "/api/capabilities/evaluate",
        json={"subject_id": "acct-2", "contact_allowed": False, **_HIGH},
    )
    assert resp.json()["disposition"] == "restricted"

    resp = await auth_client.post(
        "/api/capabilities",
        json={"capability_key": "draft-cap", "name": "Draft", "maturity": "concept"},
    )
    cap = resp.json()
    resp = await auth_client.post(
        "/api/capabilities/evaluate",
        json={"capability_id": cap["id"], "subject_id": "acct-3", **_HIGH},
    )
    body = resp.json()
    assert body["disposition"] == "future_opportunity"
    assert body["engineering_work_allowed"] is False
    assert "review" in body["engineering_work_reason"].lower()


async def test_capabilities_and_assessments_are_tenant_scoped(auth_client, test_db_session, second_org):
    from sqlalchemy import select
    from aios.governance.security import SecurityEvent

    cap = Capability(
        org_id=second_org.id,
        capability_key="secret-cap",
        name="Secret",
        maturity="production",
        is_commercially_available=True,
    )
    test_db_session.add(cap)
    await test_db_session.commit()
    await test_db_session.refresh(cap)

    resp = await auth_client.get("/api/capabilities")
    assert all(c["capability_key"] != "secret-cap" for c in resp.json()["items"])

    resp = await auth_client.post(
        "/api/capabilities/evaluate",
        json={"capability_id": cap.id, "subject_id": "acct-4", **_HIGH},
    )
    assert resp.status_code == 404, resp.text
    assessments = await auth_client.get("/api/capabilities/assessments")
    assert all(a["subject_id"] != "secret-cap" for a in assessments.json()["items"])

    rows = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        )
    ).scalars().all()
    assert any(
        e.payload.get("metric") == "cross_tenant_block"
        and e.payload.get("resource_type") == "Capability"
        and e.payload.get("resource_org_id") == second_org.id
        and e.payload.get("capability_id") == cap.id
        and e.source == "capabilities.api.evaluate"
        for e in rows
    )


async def test_blueprint_cross_tenant_records_metric(auth_client, test_db_session, second_org):
    from sqlalchemy import select
    from aios.governance.security import SecurityEvent

    cap = Capability(
        org_id=second_org.id,
        capability_key="secret-blueprint-cap",
        name="Secret blueprint",
        maturity="production",
        is_commercially_available=True,
    )
    test_db_session.add(cap)
    await test_db_session.commit()
    await test_db_session.refresh(cap)

    resp = await auth_client.post(
        "/api/capabilities/blueprint",
        json={"capability_id": cap.id, "agent_type": "support", **_HIGH},
    )
    assert resp.status_code == 404, resp.text

    rows = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        )
    ).scalars().all()
    assert any(
        e.payload.get("metric") == "cross_tenant_block"
        and e.payload.get("resource_type") == "Capability"
        and e.payload.get("resource_org_id") == second_org.id
        and e.payload.get("capability_id") == cap.id
        and e.source == "api.capabilities.blueprint"
        for e in rows
    )


async def test_invalid_maturity_and_score_rejected(auth_client):
    resp = await auth_client.post(
        "/api/capabilities",
        json={"capability_key": "x", "name": "X", "maturity": "magic"},
    )
    assert resp.status_code == 400

    resp = await auth_client.post(
        "/api/capabilities/evaluate",
        json={"subject_id": "acct-5", "feasibility": 2.0},
    )
    assert resp.status_code == 400


async def test_capability_mutating_track_c_autonomous_guard(auth_client):
    payload = {
        "capability_key": "auto-cap",
        "name": "Auto",
        "maturity": "pilot",
        "is_commercially_available": True,
        "track": "C",
        "autonomous": True,
    }
    resp = await auth_client.post("/api/capabilities", json=payload)
    assert resp.status_code == 403
    assert "evidence" in resp.text.lower() or "Founder" in resp.text

    payload["evidence"] = ["pilot-log"]
    payload["founder_approved"] = True
    resp = await auth_client.post("/api/capabilities", json=payload)
    assert resp.status_code == 200, resp.text

    cap_id = resp.json()["id"]
    bad_eval = {"capability_id": cap_id, "subject_id": "acct-x", "track": "C", "autonomous": True, **_HIGH}
    resp = await auth_client.post("/api/capabilities/evaluate", json=bad_eval)
    assert resp.status_code == 403
    good_eval = {**bad_eval, "evidence": ["log"], "founder_approved": True}
    resp = await auth_client.post("/api/capabilities/evaluate", json=good_eval)
    assert resp.status_code == 200, resp.text


async def test_capability_track_c_mode_markers_and_evidence_keys_fail_closed(auth_client):
    base = {
        "capability_key": "mode-cap",
        "name": "Mode",
        "maturity": "pilot",
        "is_commercially_available": True,
        "track": "C",
        "optimization_mode": "track_c_autonomous",
    }
    resp = await auth_client.post("/api/capabilities", json=base)
    assert resp.status_code == 403

    resp = await auth_client.post(
        "/api/capabilities",
        json={**base, "track_c_evidence": ["ev-1"], "founder_approved": True},
    )
    assert resp.status_code == 200, resp.text

    eval_base = {"subject_id": "acct-mode", "track": "C", "mode": "auto_optimize", **_HIGH}
    resp = await auth_client.post("/api/capabilities/evaluate", json=eval_base)
    assert resp.status_code == 403

    resp = await auth_client.post(
        "/api/capabilities/evaluate",
        json={
            **eval_base,
            "permissions": {"evidence_refs": ["ref-1"], "founder_approved": True},
        },
    )
    assert resp.status_code == 200, resp.text

    resp = await auth_client.post(
        "/api/capabilities/evaluate",
        json={**eval_base, "evidence": "   ", "founder_approved": True},
    )
    assert resp.status_code == 403
