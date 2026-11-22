"""Privacy API: processing registry + deterministic evaluation + rights requests."""

from aios.governance.privacy import evaluate_processing


async def test_privacy_activity_requires_core_fields(auth_client):
    resp = await auth_client.post("/api/privacy/activities", json={"activity_key": "lia_outreach"})
    assert resp.status_code == 400, resp.text

    resp = await auth_client.post(
        "/api/privacy/activities",
        json={
            "activity_key": "lia_outreach",
            "purpose": "sales outreach",
            "legal_basis": "legitimate_interest",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "draft"


async def test_privacy_evaluation_fails_closed_without_activity(auth_client):
    resp = await auth_client.post(
        "/api/privacy/evaluate",
        json={"activity_key": "nope", "action": "read", "purpose": "sales outreach"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"] == "deny"


async def test_privacy_evaluation_allows_approved_activity(auth_client, test_db_session):
    from sqlalchemy import select

    from aios.governance.privacy import ProcessingActivity

    created = (
        await auth_client.post(
            "/api/privacy/activities",
            json={
                "activity_key": "lia_outreach",
                "purpose": "sales outreach",
                "legal_basis": "legitimate_interest",
                "legal_basis_evidence": "LIA-2026-01",
                "necessity_assessment": "minimal contact fields",
                "retention_days": 180,
            },
        )
    )
    assert created.status_code == 200, created.text
    activity_id = created.json()["id"]
    activity = (
        await test_db_session.execute(select(ProcessingActivity).where(ProcessingActivity.id == activity_id))
    ).scalar_one()
    activity.status = "approved"
    await test_db_session.commit()

    resp = await auth_client.post(
        "/api/privacy/evaluate",
        json={"activity_key": "lia_outreach", "action": "read", "purpose": "sales outreach"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"] == "allow"


async def test_privacy_request_is_created(auth_client):
    resp = await auth_client.post(
        "/api/privacy/requests",
        json={"subject_identifier": "user_1", "request_type": "access", "due_days": 15},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "received"
    assert "due_at" in body
    assert evaluate_processing(None, actor_org_id="o", tenant_org_id="o", action="read")[0] == "deny"
