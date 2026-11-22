"""Slack API: read-only taxonomy + migration gate; never mutates channels."""


async def test_read_only_proposal_endpoints(auth_client):
    taxonomy = await auth_client.get("/api/slack/taxonomy")
    assert taxonomy.status_code == 200, taxonomy.text
    assert "dept-sales" in taxonomy.json()["areas"]["departments"]

    sor = await auth_client.get("/api/slack/system-of-record")
    assert sor.json()["systems"]["tasks"] == "aios_ocp"
    assert sor.json()["systems"]["customer_information"] == "aios_crm"

    steps = await auth_client.get("/api/slack/migration-steps")
    assert any("founder approval" in s for s in steps.json()["steps"])

    guards = await auth_client.get("/api/slack/guardrails")
    assert guards.json()["slack_may_become_decision"] is False
    assert guards.json()["channel_creation_blocked"] is True


async def test_channel_validation_enforces_taxonomy(auth_client):
    resp = await auth_client.post(
        "/api/slack/validate-channel", json={"area": "departments", "name": "dept-sales"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["valid"] is True

    for area, name in (
        ("departments", "agent-sales"),
        ("departments", "collab-sales"),
        ("unknown", "dept-sales"),
    ):
        resp = await auth_client.post(
            "/api/slack/validate-channel", json={"area": area, "name": name}
        )
        assert resp.status_code == 400


async def test_migration_gate_requires_inventory_map_and_founder(
    auth_client, test_db_session, test_org, test_user
):
    gate = await auth_client.get("/api/slack/migration-gate")
    assert gate.json()["allowed"] is False
    assert "real workspace not inventoried" in gate.json()["reasons"]

    test_org.extra_data = {
        "slack_workspace_inventoried": True,
        "slack_migration_map_approved": True,
    }
    await test_db_session.commit()
    gate = await auth_client.get("/api/slack/migration-gate")
    assert "Founder approval required" in gate.json()["reasons"]

    test_org.extra_data = {
        "slack_workspace_inventoried": True,
        "slack_migration_map_approved": True,
        "founder_user_id": test_user.id,
    }
    await test_db_session.commit()
    gate = await auth_client.get("/api/slack/migration-gate")
    assert gate.json() == {"allowed": True, "reasons": []}


async def test_no_channel_mutation_route(auth_client):
    for method in ("POST", "PATCH", "DELETE"):
        resp = await auth_client.request(method, "/api/slack/channels", json={"name": "dept-x"})
        assert resp.status_code in (404, 405)
