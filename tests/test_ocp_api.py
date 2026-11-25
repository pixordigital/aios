"""OCP API: tenants only touch their own tasks and only the Founder decides levels 2-3."""

from aios.governance.ocp import AuthorityGrant, DECISION_PROTOCOL_FIELDS, DecisionRecord, SharedTask


async def test_department_and_task_lifecycle(auth_client, test_db_session, test_org):
    test_org.extra_data = {"ocp": {"strict_default_deny": False}}
    await test_db_session.commit()
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
    test_org.extra_data = {"ocp": {"strict_default_deny": False}}
    await test_db_session.commit()
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

    test_org.extra_data = {"ocp": {"strict_default_deny": False}, "founder_user_id": test_user.id}
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
    body = resp.json()
    assert all(t["title"] != "Secret task" for t in body["items"])
    assert body["truncated"] is False
    assert "total" not in body


async def test_task_list_bounded_page_and_offset(auth_client, test_db_session, test_org, second_org):
    for i in range(3):
        test_db_session.add(SharedTask(org_id=test_org.id, title=f"Own {i}"))
    test_db_session.add(SharedTask(org_id=second_org.id, title="Foreign"))
    await test_db_session.commit()

    first = await auth_client.get("/api/ocp/tasks", params={"limit": 2})
    assert first.status_code == 200, first.text
    body = first.json()
    assert [t["title"] for t in body["items"]] == ["Own 2", "Own 1"]
    assert body["truncated"] is True
    assert "total" not in body

    second = await auth_client.get("/api/ocp/tasks", params={"limit": 2, "offset": 2})
    assert second.status_code == 200, second.text
    body = second.json()
    assert [t["title"] for t in body["items"]] == ["Own 0"]
    assert body["truncated"] is False

    for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
        bad = await auth_client.get("/api/ocp/tasks", params=params)
        assert bad.status_code == 422, bad.text


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
    test_org.extra_data = {"ocp": {"strict_default_deny": False}}
    await test_db_session.commit()
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

    test_org.extra_data = {"ocp": {"strict_default_deny": False}, "founder_user_id": test_user.id}
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


async def test_decision_list_get_and_external_approval_link(auth_client, test_db_session, test_org):
    test_org.extra_data = {"ocp": {"strict_default_deny": False}}
    await test_db_session.commit()
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
        json={"ref_type": "manual", "ref_id": "pa-1", "status": "approved", "note": "bridge"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    refs = body["external_approvals"]
    assert refs and refs[0]["ref_type"] == "manual"
    assert refs[0]["ref_id"] == "pa-1"
    assert refs[0]["linked_by_type"] == "human"
    bridge = body["approval_bridge"]
    assert bridge["unified"] is False
    assert bridge["mode"] == "external_refs_only"
    assert bridge["external_approval_count"] == 1
    assert bridge["statuses"] == ["approved"]
    assert bridge["ref_types"] == ["manual"]
    assert "PendingAction/ApprovalManager" in bridge["limitation"]

    bad_type = await auth_client.post(
        f"/api/ocp/decisions/{decision_id}/link-approval",
        json={"ref_type": "bogus", "ref_id": "x"},
    )
    assert bad_type.status_code == 400
    assert "invalid approval bridge ref_type" in bad_type.json()["detail"]
    bad_status = await auth_client.post(
        f"/api/ocp/decisions/{decision_id}/link-approval",
        json={"ref_type": "manual", "ref_id": "x", "status": "bogus"},
    )
    assert bad_status.status_code == 400
    assert "invalid approval bridge status" in bad_status.json()["detail"]

    bridge_resp = await auth_client.get(f"/api/ocp/decisions/{decision_id}/approval-bridge")
    assert bridge_resp.status_code == 200, bridge_resp.text
    bridge_body = bridge_resp.json()
    assert bridge_body["decision_id"] == decision_id
    assert bridge_body["approval_bridge"]["unified"] is False
    assert bridge_body["approval_bridge"]["external_approval_count"] == 1
    assert len(bridge_body["external_approvals"]) == 1


async def test_pending_action_link_uses_db_status_not_caller_status(auth_client, test_db_session, test_org):
    from aios.db.models import PendingAction as DBAction

    test_org.extra_data = {"ocp": {"strict_default_deny": False}}
    action = DBAction(org_id=test_org.id, tool_name="test", tool_args={}, status="pending")
    test_db_session.add(action)
    await test_db_session.commit()

    full = {f: "x" for f in DECISION_PROTOCOL_FIELDS}
    created = await auth_client.post(
        "/api/ocp/decisions",
        json={"title": "Bridge from action", "change_type": "new_workflow", "justification": full},
    )
    assert created.status_code == 200, created.text
    decision_id = created.json()["id"]

    resp = await auth_client.post(
        f"/api/ocp/decisions/{decision_id}/link-approval",
        json={"ref_type": " PENDING_ACTION ", "ref_id": action.id, "status": "approved"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "proposed"  # link never auto-approves the DecisionRecord
    refs = body["external_approvals"]
    assert len(refs) == 1
    assert refs[0]["ref_type"] == "pending_action"
    assert refs[0]["ref_id"] == action.id
    assert refs[0]["status"] == "pending"  # derived from DB row, caller said approved
    assert refs[0]["verified_by_db"] is True
    assert body["approval_bridge"]["unified"] is False
    assert body["approval_bridge"]["mode"] == "external_refs_only"
    assert body["approval_bridge"]["statuses"] == ["pending"]
    bridge_resp = await auth_client.get(f"/api/ocp/decisions/{decision_id}/approval-bridge")
    assert bridge_resp.json()["external_approvals"][0]["verified_by_db"] is True


async def test_caller_reported_refs_flagged_not_db_verified(auth_client, test_db_session, test_org):
    test_org.extra_data = {"ocp": {"strict_default_deny": False}}
    await test_db_session.commit()
    full = {f: "x" for f in DECISION_PROTOCOL_FIELDS}
    created = await auth_client.post(
        "/api/ocp/decisions",
        json={"title": "Caller-reported refs", "change_type": "new_workflow", "justification": full},
    )
    assert created.status_code == 200, created.text
    decision_id = created.json()["id"]

    for ref_type, ref_id in (("approval_manager", "am-1"), ("manual", "manual-1")):
        resp = await auth_client.post(
            f"/api/ocp/decisions/{decision_id}/link-approval",
            json={
                "ref_type": ref_type,
                "ref_id": ref_id,
                "status": "approved",
                "note": "caller reported",
            },
        )
        assert resp.status_code == 200, resp.text
        refs = resp.json()["external_approvals"]
        assert refs[-1]["ref_type"] == ref_type
        assert refs[-1]["status"] == "approved"
        assert refs[-1]["note"] == "caller reported"
        assert refs[-1]["verified_by_db"] is False

    bridge_resp = await auth_client.get(f"/api/ocp/decisions/{decision_id}/approval-bridge")
    assert bridge_resp.status_code == 200, bridge_resp.text
    body = bridge_resp.json()
    assert body["decision_status"] == "proposed"
    assert body["approval_bridge"]["unified"] is False
    assert [r["verified_by_db"] for r in body["external_approvals"]] == [False, False]


async def test_pending_action_link_rejects_unknown_and_cross_org(
    auth_client, test_db_session, test_org, second_org
):
    from aios.db.models import PendingAction as DBAction

    test_org.extra_data = {"ocp": {"strict_default_deny": False}}
    foreign = DBAction(org_id=second_org.id, tool_name="test", tool_args={}, status="approved")
    test_db_session.add(foreign)
    await test_db_session.commit()

    full = {f: "x" for f in DECISION_PROTOCOL_FIELDS}
    created = await auth_client.post(
        "/api/ocp/decisions",
        json={"title": "Guarded bridge", "change_type": "new_workflow", "justification": full},
    )
    assert created.status_code == 200, created.text
    decision_id = created.json()["id"]
    before = created.json()["justification"]

    for ref_id in ("missing-action", foreign.id):
        resp = await auth_client.post(
            f"/api/ocp/decisions/{decision_id}/link-approval",
            json={"ref_type": "pending_action", "ref_id": ref_id, "status": "approved"},
        )
        assert resp.status_code == 404, resp.text
        current = await auth_client.get(f"/api/ocp/decisions/{decision_id}")
        assert current.json()["justification"] == before


async def test_task_approval_links_read_only_bridge(auth_client, test_db_session, test_org):
    test_org.extra_data = {"ocp": {"strict_default_deny": False}}
    await test_db_session.commit()
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
    body = resp.json()
    items = body["items"]
    assert len(items) == 1
    assert items[0]["decision_id"] == decision_id
    assert items[0]["external_approvals"][0]["ref_id"] == "am-1"
    assert items[0]["approval_bridge"]["unified"] is False
    assert body["approval_bridge"]["unified"] is False
    assert body["approval_bridge"]["linked_decision_count"] == 1
    assert body["approval_bridge"]["external_approval_count"] == 1


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
    body = resp.json()
    assert body["strict_default_deny"] is True
    assert body["mode"] == "strict_default_deny"
    assert body["approval_bridge"]["unified"] is False
    assert body["approval_bridge"]["mode"] == "external_refs_only"
    assert "pending_action" in body["approval_bridge"]["ref_types"]

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


async def test_ocp_track_c_autonomous_mutation_fail_closed(auth_client, test_db_session, test_org, test_user):
    """Narrow latent-fail-open guard: Track C/autonomous markers in mutating OCP payloads."""
    test_org.extra_data = {"ocp": {"strict_default_deny": False}}
    await test_db_session.commit()
    base = {"title": "Auto task", "track": "C", "autonomous": True}

    resp = await auth_client.post("/api/ocp/tasks", json=base)
    assert resp.status_code == 403
    assert "requires evidence" in resp.json()["detail"]

    resp = await auth_client.post("/api/ocp/tasks", json={**base, "evidence": {"source": "test"}})
    assert resp.status_code == 403
    assert "Founder approval" in resp.json()["detail"]

    test_org.extra_data = {"ocp": {"strict_default_deny": False}, "founder_user_id": test_user.id}
    await test_db_session.commit()
    resp = await auth_client.post(
        "/api/ocp/tasks",
        json={**base, "evidence": {"source": "test"}, "founder_approved": True},
    )
    assert resp.status_code == 200, resp.text

    # mode marker also guarded
    resp = await auth_client.post(
        "/api/ocp/goals",
        json={"title": "G2", "track": "C", "mode": "track_c_autonomous", "evidence": {"x": 1}},
    )
    # founder is set, but evidence+founder_approved required in payload
    assert resp.status_code == 403
    assert "Founder approval" in resp.json()["detail"]
    resp = await auth_client.post(
        "/api/ocp/goals",
        json={"title": "G2", "track": "C", "mode": "track_c_autonomous", "evidence": {"x": 1}, "founder_approved": True},
    )
    assert resp.status_code == 200, resp.text


async def test_ocp_policy_put_track_c_autonomous_guard(auth_client, test_db_session, test_org, test_user):
    """PUT /api/ocp/policy must fail-closed on Track C/autonomous markers."""
    base = {"strict_default_deny": True, "track": "C", "autonomous": True}

    resp = await auth_client.put("/api/ocp/policy", json=base)
    assert resp.status_code == 403
    assert "requires evidence" in resp.json()["detail"]

    resp = await auth_client.put("/api/ocp/policy", json={**base, "evidence": {"source": "test"}})
    assert resp.status_code == 403
    assert "Founder approval" in resp.json()["detail"]

    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()
    resp = await auth_client.put(
        "/api/ocp/policy",
        json={**base, "evidence": {"source": "test"}, "founder_approved": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["strict_default_deny"] is True


async def test_ocp_org_scope_guard_uses_organization_id_only(test_db_session, test_org, second_org):
    """Organization scoped by .id; arbitrary resources never fall back to .id."""
    import pytest
    from fastapi import HTTPException
    from sqlalchemy import select

    from aios.api.deps import verify_org_access, verify_org_access_async
    from aios.governance.security import SecurityEvent

    verify_org_access(test_org.id, test_org)
    await verify_org_access_async(test_org.id, test_org, db=test_db_session)

    class Arbitrary:
        id = test_org.id

    with pytest.raises(HTTPException) as exc_no_scope:
        verify_org_access(test_org.id, Arbitrary())
    assert exc_no_scope.value.status_code == 404

    with pytest.raises(HTTPException) as exc_mismatch:
        await verify_org_access_async(
            second_org.id, test_org, db=test_db_session, source="api.ocp.get_policy"
        )
    assert exc_mismatch.value.status_code == 404
    evt = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.source == "api.ocp.get_policy")
        )
    ).scalar_one()
    assert evt.payload["resource_org_id"] == test_org.id


async def test_authority_grants_list_bounded_page_and_offset(
    auth_client, test_db_session, test_org, second_org
):
    own = [
        AuthorityGrant(
            org_id=test_org.id, subject_type="human", subject_id=f"u{i}",
            role="operator", actions=["task:create"],
        )
        for i in range(3)
    ]
    own[2].subject_type = "agent"
    foreign = AuthorityGrant(
        org_id=second_org.id, subject_type="human", subject_id="foreign",
        role="operator", actions=["task:create"],
    )
    test_db_session.add_all([*own, foreign])
    await test_db_session.commit()

    all_resp = await auth_client.get("/api/ocp/authority-grants")
    assert all_resp.status_code == 200, all_resp.text
    all_body = all_resp.json()
    assert all_body["truncated"] is False
    assert "total" not in all_body
    assert {g["id"] for g in all_body["items"]} == {g.id for g in own}
    assert set(all_body["items"][0]) == {
        "id", "department_id", "subject_type", "subject_id", "role", "actions",
        "resources", "scope", "max_decision_level", "valid_from", "valid_until",
        "revoked_at", "granted_by",
    }

    first = await auth_client.get("/api/ocp/authority-grants", params={"limit": 2})
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["items"]) == 2
    assert body["truncated"] is True
    assert "total" not in body

    second = await auth_client.get(
        "/api/ocp/authority-grants", params={"limit": 2, "offset": 2}
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert len(body["items"]) == 1
    assert body["truncated"] is False

    own_ids = {g["id"] for g in all_body["items"]}
    first_ids = {g["id"] for g in first.json()["items"]}
    second_ids = {g["id"] for g in second.json()["items"]}
    assert first_ids | second_ids == own_ids
    assert first_ids.isdisjoint(second_ids)

    filtered = await auth_client.get(
        "/api/ocp/authority-grants", params={"subject_type": "agent"}
    )
    assert filtered.status_code == 200, filtered.text
    assert [g["subject_id"] for g in filtered.json()["items"]] == [own[2].subject_id]

    for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
        bad = await auth_client.get("/api/ocp/authority-grants", params=params)
        assert bad.status_code == 422, bad.text
