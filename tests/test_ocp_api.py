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


async def test_decision_list_get_and_external_approval_link(auth_client):
    full = {f: "x" for f in DECISION_PROTOCOL_FIELDS}
    resp = await auth_client.post(
        "/api/ocp/decisions",
        json={"title": "New workflow", "change_type": "new_workflow", "justification": full},
    )
    assert resp.status_code == 200, resp.text
    decision_id = resp.json()["id"]

    resp = await auth_client.get("/api/ocp/decisions")
    assert resp.status_code == 200
    assert any(d["id"] == decision_id for d in resp.json()["items"])

    resp = await auth_client.get(f"/api/ocp/decisions/{decision_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "New workflow"

    resp = await auth_client.post(
        f"/api/ocp/decisions/{decision_id}/link-approval",
        json={"ref_type": "pending_action", "ref_id": "pa-1", "status": "approved", "note": "bridge"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    refs = body["external_approvals"]
    assert refs and refs[0]["ref_type"] == "pending_action"
    assert refs[0]["ref_id"] == "pa-1"
    bridge = body["approval_bridge"]
    assert bridge["unified"] is False
    assert bridge["mode"] == "external_refs_only"
    assert bridge["external_approval_count"] == 1
    assert "PendingAction/ApprovalManager" in bridge["limitation"]


async def test_task_approval_links_read_only_bridge(auth_client, test_db_session):
    task_resp = await auth_client.post("/api/ocp/tasks", json={"title": "Bridge task"})
    task_id = task_resp.json()["id"]
    full = {f: "x" for f in DECISION_PROTOCOL_FIELDS}
    d = await auth_client.post(
        "/api/ocp/decisions",
        json={"title": "D", "change_type": "new_workflow", "justification": full, "linked_task_ids": [task_id]},
    )
    decision_id = d.json()["id"]
    await auth_client.post(
        f"/api/ocp/decisions/{decision_id}/link-approval",
        json={"ref_type": "approval_manager", "ref_id": "am-1", "status": "pending"},
    )
    resp = await auth_client.get(f"/api/ocp/tasks/{task_id}/approval-links")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["decision_id"] == decision_id
    assert items[0]["external_approvals"][0]["ref_id"] == "am-1"


async def test_ocp_strict_default_deny_blocks_ungranted_action(
    auth_client, test_db_session, test_org, test_user
):
    # Founder needed to bootstrap grants under strict mode; founder_bypass allows
    # authority:grant/authority:revoke for explicit Founder/owner.
    test_org.extra_data = {"ocp": {"strict_default_deny": True}, "founder_user_id": test_user.id}
    await test_db_session.commit()
    resp = await auth_client.post("/api/ocp/tasks", json={"title": "Needs grant"})
    assert resp.status_code == 403
    assert "strict_default_deny" in resp.json()["detail"]

    # Add matching grant -> allowed.
    grant_resp = await auth_client.post(
        "/api/ocp/authority-grants",
        json={
            "subject_type": "human",
            "subject_id": test_user.id,
            "role": "operator",
            "actions": ["task:create"],
        },
    )
    assert grant_resp.status_code == 200, grant_resp.text
    resp = await auth_client.post("/api/ocp/tasks", json={"title": "Granted"})
    assert resp.status_code == 200, resp.text


async def test_ocp_policy_get_put_founder_only(auth_client, test_db_session, test_org, test_user):
    resp = await auth_client.get("/api/ocp/policy")
    assert resp.status_code == 200, resp.text
    assert resp.json()["strict_default_deny"] is False
    assert resp.json()["mode"] == "policy_if_configured"
    assert resp.json()["approval_bridge"]["unified"] is False

    resp = await auth_client.put("/api/ocp/policy", json={"strict_default_deny": True})
    assert resp.status_code == 403

    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()
    resp = await auth_client.put("/api/ocp/policy", json={"strict_default_deny": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["strict_default_deny"] is True
    assert resp.json()["mode"] == "strict_default_deny"

    resp = await auth_client.get("/api/ocp/policy")
    assert resp.status_code == 200
    assert resp.json()["strict_default_deny"] is True

    # strict mode now blocks mutating endpoint without grant
    blocked = await auth_client.post("/api/ocp/goals", json={"title": "G"})
    assert blocked.status_code == 403
    assert "strict_default_deny" in blocked.json()["detail"]

    grant_resp = await auth_client.post(
        "/api/ocp/authority-grants",
        json={"subject_type": "human", "subject_id": test_user.id, "role": "op", "actions": ["goal:create"]},
    )
    assert grant_resp.status_code == 200, grant_resp.text
    ok = await auth_client.post("/api/ocp/goals", json={"title": "G"})
    assert ok.status_code == 200, ok.text
