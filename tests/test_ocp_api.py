"""OCP API: tenants only touch their own tasks and only the Founder decides levels 2-3."""

from aios.governance.ocp import DECISION_PROTOCOL_FIELDS, DecisionRecord, SharedTask


async def test_department_and_task_lifecycle(auth_client):
    resp = await auth_client.post("/api/ocp/departments", json={"name": "Sales", "slug": "sales"})
    assert resp.status_code == 200, resp.text
    dept_id = resp.json()["id"]

    resp = await auth_client.post(
        "/api/ocp/tasks",
        json={"title": "Qualify lead", "responsible_department_id": dept_id},
    )
    assert resp.status_code == 200, resp.text
    task = resp.json()
    assert task["status"] == "new"

    resp = await auth_client.post(f"/api/ocp/tasks/{task['id']}/transition", json={"target": "completed"})
    assert resp.status_code == 400  # cannot skip the ladder

    resp = await auth_client.post(f"/api/ocp/tasks/{task['id']}/transition", json={"target": "triage"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "triage"
    assert resp.json()["audit_history"][-1]["to"] == "triage"


async def test_decision_requires_full_protocol_and_founder(auth_client, test_db_session, test_org, test_user):
    resp = await auth_client.post(
        "/api/ocp/decisions",
        json={"title": "New integration", "change_type": "new_integration", "justification": {"proposal": "x"}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["level"] == 2
    assert "risks" in body["missing_fields"]

    resp = await auth_client.post(f"/api/ocp/decisions/{body['id']}/decide", json={"approve": True})
    assert resp.status_code == 403  # admin is not automatically the Founder

    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()
    resp = await auth_client.post(f"/api/ocp/decisions/{body['id']}/decide", json={"approve": True})
    assert resp.status_code == 400  # incomplete protocol still blocked

    full = {f: "x" for f in DECISION_PROTOCOL_FIELDS}
    resp = await auth_client.post(
        "/api/ocp/decisions",
        json={"title": "New integration", "change_type": "new_integration", "justification": full},
    )
    decision_id = resp.json()["id"]
    resp = await auth_client.post(f"/api/ocp/decisions/{decision_id}/decide", json={"approve": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"


async def test_tasks_are_tenant_scoped(auth_client, test_db_session):
    from aios.db.models import Organization
    from aios.governance.ocp import SharedTask

    other = Organization(name="Other", slug="other-org")
    test_db_session.add(other)
    await test_db_session.flush()
    test_db_session.add(SharedTask(org_id=other.id, title="Secret task"))
    await test_db_session.commit()

    resp = await auth_client.get("/api/ocp/tasks")
    assert resp.status_code == 200
    assert all(t["title"] != "Secret task" for t in resp.json()["items"])


async def test_bootstrap_default_departments_founder_only(
    auth_client, test_db_session, test_org, test_user
):
    resp = await auth_client.post("/api/ocp/departments/bootstrap-defaults")
    assert resp.status_code == 403

    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()
    resp = await auth_client.post("/api/ocp/departments/bootstrap-defaults")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created_count"] == body["defaults"] == 8
    slugs = {d["slug"] for d in body["created"]}
    assert {"executive-secretary", "commercial", "operations", "engineering", "governance",
            "product", "security-ai-soc", "privacy-lgpd"} == slugs

    resp = await auth_client.post("/api/ocp/departments/bootstrap-defaults")
    assert resp.status_code == 200
    assert resp.json()["created_count"] == 0


async def test_decision_execute_transitions_linked_task(
    auth_client, test_db_session, test_org, test_user
):
    task_resp = await auth_client.post(
        "/api/ocp/tasks",
        json={"title": "Wire approval to task"},
    )
    assert task_resp.status_code == 200, task_resp.text
    task_id = task_resp.json()["id"]

    await auth_client.post(f"/api/ocp/tasks/{task_id}/transition", json={"target": "triage"})
    await auth_client.post(f"/api/ocp/tasks/{task_id}/transition", json={"target": "ready"})
    task_check = await test_db_session.get(SharedTask, task_id)
    assert task_check.status == "ready"

    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()

    full = {f: "x" for f in DECISION_PROTOCOL_FIELDS}
    decision_resp = await auth_client.post(
        "/api/ocp/decisions",
        json={"title": "New integration", "change_type": "new_integration", "justification": full},
    )
    assert decision_resp.status_code == 200, decision_resp.text
    decision_id = decision_resp.json()["id"]
    decision = await test_db_session.get(DecisionRecord, decision_id)
    decision.linked_task_ids = [task_id]
    await test_db_session.commit()

    resp = await auth_client.post(f"/api/ocp/decisions/{decision_id}/decide", json={"approve": True})
    assert resp.status_code == 200, resp.text

    resp = await auth_client.post(
        f"/api/ocp/decisions/{decision_id}/execute", json={"task_ids": [task_id]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "executed"

    task = await test_db_session.get(SharedTask, task_id)
    assert task.status == "in_progress"
