"""Innovation API: declared experiments, deterministic results, Founder decisions."""

from sqlalchemy import select

from aios.db.models import Organization
from aios.governance.innovation import Experiment


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


async def test_experiments_are_tenant_scoped(auth_client, test_db_session):
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
