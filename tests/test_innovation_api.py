"""Innovation API: declared experiments, deterministic results, Founder decisions."""

from datetime import datetime, timedelta

from sqlalchemy import select

from aios.db.models import Organization
from aios.governance.innovation import Experiment, Hypothesis
from aios.governance.security import SECURITY_METRIC_EVENT_TYPES, SecurityEvent


def _decl(hypothesis_id: str) -> dict:
    return {
        "hypothesis_id": hypothesis_id,
        "title": "Qualify dealership leads",
        "mvp_type": "commercial_mvp",
        "riskiest_assumption": "SMBs answer outbound",
        "metric_name": "qualified_rate",
        "baseline": 0.1,
        "sample_size": 50,
        "success_threshold": 0.2,
        "direction": "increase",
        "cost_cap_brl": 500.0,
        "time_cap_days": 14,
        "owner_id": "owner-1",
        "stop_conditions": "no replies after 20 sends",
    }


async def _hypothesis(auth_client) -> str:
    resp = await auth_client.post(
        "/api/innovation/hypotheses",
        json={"title": "Outbound works", "kind": "value", "riskiest_assumption": "reply rate"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def test_experiment_ladder_scoreboard_and_founder_decision(
    auth_client, test_db_session, test_org, test_user
):
    h_id = await _hypothesis(auth_client)
    resp = await auth_client.post("/api/innovation/experiments", json=_decl(h_id))
    assert resp.status_code == 200, resp.text
    exp_id = resp.json()["id"]

    resp = await auth_client.post(
        f"/api/innovation/experiments/{exp_id}/evaluate",
        json={"observed": 0.31, "spent_brl": 120.0},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"] == "success"
    assert resp.json()["suggested_decision"] == "persevere"

    resp = await auth_client.post(f"/api/innovation/experiments/{exp_id}/decide", json={})
    assert resp.status_code == 403  # admin is not Founder

    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()
    resp = await auth_client.post(f"/api/innovation/experiments/{exp_id}/decide", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["decision"] == "persevere"

    score = await auth_client.get("/api/innovation/scoreboard")
    assert score.status_code == 200
    assert score.json()["finished"] == 1
    assert score.json()["validated"] == 1


async def test_budget_breach_stops_and_decides_stop(auth_client, test_db_session, test_org, test_user):
    h_id = await _hypothesis(auth_client)
    resp = await auth_client.post("/api/innovation/experiments", json=_decl(h_id))
    exp_id = resp.json()["id"]
    resp = await auth_client.post(
        f"/api/innovation/experiments/{exp_id}/evaluate",
        json={"observed": 0.9, "spent_brl": 600.0},
    )
    assert resp.json()["result"] == "stopped"
    assert resp.json()["suggested_decision"] == "stop"

    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()
    resp = await auth_client.post(f"/api/innovation/experiments/{exp_id}/decide", json={})
    assert resp.json()["decision"] == "stop"


async def test_incomplete_declaration_rejected(auth_client):
    h_id = await _hypothesis(auth_client)
    decl = _decl(h_id)
    decl.pop("stop_conditions")
    resp = await auth_client.post("/api/innovation/experiments", json=decl)
    assert resp.status_code == 400
    assert "stop_conditions" in resp.text


async def test_hypothesis_linkage_track_c_and_mvp_promotion_guards(
    auth_client, test_db_session, test_org, test_user
):
    decl = _decl(None)
    decl["hypothesis_id"] = None
    resp = await auth_client.post("/api/innovation/experiments", json=decl)
    assert resp.status_code == 400
    assert "hypothesis_id_or_orphan_justification" in resp.text

    decl["permissions"] = {"orphan_justification": "founder exploratory request"}
    resp = await auth_client.post("/api/innovation/experiments", json=decl)
    assert resp.status_code == 200

    h_id = await _hypothesis(auth_client)
    track_c = _decl(h_id)
    track_c["mvp_type"] = "commercial_mvp"
    track_c["permissions"] = {"track": "C", "autonomous": True}
    resp = await auth_client.post("/api/innovation/experiments", json=track_c)
    assert resp.status_code == 400
    assert "track_c_evidence" in resp.text

    track_c["permissions"] = {"track": "C", "autonomous": True, "evidence": ["pilot-log"]}
    resp = await auth_client.post("/api/innovation/experiments", json=track_c)
    assert resp.status_code == 403
    track_c["founder_approved"] = True
    resp = await auth_client.post("/api/innovation/experiments", json=track_c)
    assert resp.status_code == 200, resp.text
    exp_id = resp.json()["id"]
    resp = await auth_client.post(f"/api/innovation/experiments/{exp_id}/evaluate", json={"observed": 0.3})
    assert resp.status_code == 403
    resp = await auth_client.post(
        f"/api/innovation/experiments/{exp_id}/evaluate",
        json={"observed": 0.3, "founder_approved": True},
    )
    assert resp.status_code == 200, resp.text

    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()
    resp = await auth_client.post(
        f"/api/innovation/experiments/{exp_id}/decide",
        json={"decision": "persevere", "promote_to_production": True},
    )
    assert resp.status_code == 200

    proto = _decl(h_id)
    proto["mvp_type"] = "experimental_prototype"
    resp = await auth_client.post("/api/innovation/experiments", json=proto)
    exp_id = resp.json()["id"]
    await auth_client.post(f"/api/innovation/experiments/{exp_id}/evaluate", json={"observed": 0.3})
    resp = await auth_client.post(
        f"/api/innovation/experiments/{exp_id}/decide",
        json={"decision": "persevere", "promote_to_production": True},
    )
    assert resp.status_code == 403
    assert "review" in resp.text.lower()


async def test_experiments_are_tenant_scoped(auth_client, test_db_session, test_org):
    other = Organization(name="Other", slug="other-innov-org")
    test_db_session.add(other)
    await test_db_session.flush()
    test_db_session.add(Experiment(org_id=other.id, title="Secret experiment"))
    await test_db_session.commit()

    resp = await auth_client.get("/api/innovation/experiments")
    assert all(e["title"] != "Secret experiment" for e in resp.json()["items"])

    secret = (
        await test_db_session.execute(select(Experiment).where(Experiment.org_id == other.id))
    ).scalars().first()
    resp = await auth_client.post(f"/api/innovation/experiments/{secret.id}/decide", json={})
    assert resp.status_code == 404

    events = (
        await test_db_session.execute(
            select(SecurityEvent).where(
                SecurityEvent.org_id == test_org.id,
                SecurityEvent.event_type == SECURITY_METRIC_EVENT_TYPES["cross_tenant_block"],
                SecurityEvent.source == "api.innovation.decide",
            )
        )
    ).scalars().all()
    mismatch = [
        e
        for e in events
        if e.payload.get("resource_type") == "Experiment"
        and e.payload.get("resource_org_id") == other.id
    ]
    assert mismatch


async def test_track_b_requires_hypothesis_api(auth_client):
    decl = _decl(None)
    decl["hypothesis_id"] = None
    decl["permissions"] = {"track": "B", "orphan_justification": "explore"}
    resp = await auth_client.post("/api/innovation/experiments", json=decl)
    assert resp.status_code == 400
    assert "Track B" in resp.text or "hypothesis" in resp.text.lower()

    h_id = await _hypothesis(auth_client)
    decl["hypothesis_id"] = h_id
    resp = await auth_client.post("/api/innovation/experiments", json=decl)
    assert resp.status_code == 200, resp.text


async def test_create_experiment_cross_tenant_hypothesis_emits_metric(auth_client, test_db_session, test_org):
    other = Organization(name="Other2", slug="other-innov-org-2")
    test_db_session.add(other)
    await test_db_session.flush()
    h = Hypothesis(org_id=other.id, title="Other hyp", kind="value")
    test_db_session.add(h)
    await test_db_session.commit()

    resp = await auth_client.post("/api/innovation/experiments", json=_decl(h.id))
    assert resp.status_code == 404

    events = (
        await test_db_session.execute(
            select(SecurityEvent).where(
                SecurityEvent.org_id == test_org.id,
                SecurityEvent.event_type == SECURITY_METRIC_EVENT_TYPES["cross_tenant_block"],
                SecurityEvent.source == "api.innovation.create_experiment",
            )
        )
    ).scalars().all()
    mismatch = [
        e
        for e in events
        if e.payload.get("resource_type") == "Hypothesis"
        and e.payload.get("resource_org_id") == other.id
    ]
    assert mismatch


async def test_experiment_list_bounded_page_and_offset(
    auth_client, test_db_session, test_org, second_org
):
    base_created = datetime(2026, 1, 1)
    own = [
        Experiment(
            org_id=test_org.id, title=f"Own {i}",
            created_at=base_created + timedelta(minutes=i),
        )
        for i in range(3)
    ]
    foreign = Experiment(org_id=second_org.id, title="Foreign experiment")
    test_db_session.add_all([*own, foreign])
    await test_db_session.commit()

    all_resp = await auth_client.get("/api/innovation/experiments")
    assert all_resp.status_code == 200, all_resp.text
    all_body = all_resp.json()
    assert all_body["truncated"] is False
    assert "total" not in all_body
    assert {e["title"] for e in all_body["items"]} == {e.title for e in own}
    assert set(all_body["items"][0]) == {
        "id", "hypothesis_id", "title", "mvp_type", "metric_name", "result", "decision"
    }

    first = await auth_client.get("/api/innovation/experiments", params={"limit": 2})
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["items"]) == 2
    assert body["truncated"] is True
    assert "total" not in body

    second = await auth_client.get(
        "/api/innovation/experiments", params={"limit": 2, "offset": 2}
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert len(body["items"]) == 1
    assert body["truncated"] is False

    expected_order = [
        e.id for e in sorted(own, key=lambda e: (e.created_at, e.id), reverse=True)
    ]
    assert [e["id"] for e in all_body["items"]] == expected_order
    assert [e["id"] for e in first.json()["items"]] == expected_order[:2]
    assert [e["id"] for e in second.json()["items"]] == expected_order[2:]

    own_ids = {e["id"] for e in all_body["items"]}
    first_ids = {e["id"] for e in first.json()["items"]}
    second_ids = {e["id"] for e in second.json()["items"]}
    assert first_ids | second_ids == own_ids
    assert first_ids.isdisjoint(second_ids)

    first_repeat = await auth_client.get("/api/innovation/experiments", params={"limit": 2})
    assert [e["id"] for e in first_repeat.json()["items"]] == expected_order[:2]
    second_repeat = await auth_client.get(
        "/api/innovation/experiments", params={"limit": 2, "offset": 2}
    )
    assert [e["id"] for e in second_repeat.json()["items"]] == expected_order[2:]

    for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
        bad = await auth_client.get("/api/innovation/experiments", params=params)
        assert bad.status_code == 422, bad.text
