"""Skills lifecycle API: state ladder enforced, Founder gate for publish/deprecate."""

from sqlalchemy import select

from aios.db.models import Agent, Organization, Skill
from aios.governance.security import SecurityEvent


async def _skill(test_db_session, test_org, status="draft", org_id=None):
    agent = Agent(org_id=org_id or test_org.id, name="skill-agent", agent_type="sdr")
    test_db_session.add(agent)
    await test_db_session.flush()
    skill = Skill(
        org_id=org_id or test_org.id,
        agent_id=agent.id,
        name="lead_pattern",
        status=status,
    )
    test_db_session.add(skill)
    await test_db_session.commit()
    return skill


async def test_transition_ladder_and_founder_gate(
    auth_client, test_db_session, test_org, test_user
):
    skill = await _skill(test_db_session, test_org)

    resp = await auth_client.post(f"/api/skills/{skill.id}/transition", json={"target": "published"})
    assert resp.status_code == 400  # draft cannot skip the ladder
    assert "illegal" in resp.json()["detail"]

    for target in ("under_review", "testing", "approved"):
        resp = await auth_client.post(f"/api/skills/{skill.id}/transition", json={"target": target})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == target

    resp = await auth_client.post(f"/api/skills/{skill.id}/transition", json={"target": "published"})
    assert resp.status_code == 400  # admin is not the Founder
    assert "founder approval required" in resp.json()["detail"]

    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()
    resp = await auth_client.post(f"/api/skills/{skill.id}/transition", json={"target": "published"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": skill.id, "status": "published", "actor": test_user.id}


async def _assert_cross_tenant_skill_404(
    *, resp, test_db_session, skill, test_org, other, source: str
):
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Skill not found"
    rows = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        )
    ).scalars().all()
    assert any(
        e.payload.get("metric") == "cross_tenant_block"
        and e.payload.get("resource_type") == "Skill"
        and e.payload.get("requested_org_id") == test_org.id
        and e.payload.get("resource_org_id") == other.id
        and e.payload.get("skill_id") == skill.id
        and e.source == source
        for e in rows
    )


async def test_cross_tenant_update_records_metric(auth_client, test_db_session, test_org):
    other = Organization(name="OtherUpd", slug="other-org-upd")
    test_db_session.add(other)
    await test_db_session.flush()
    skill = await _skill(test_db_session, test_org, org_id=other.id)

    resp = await auth_client.put(f"/api/skills/{skill.id}", json={"name": "x"})
    await _assert_cross_tenant_skill_404(
        resp=resp,
        test_db_session=test_db_session,
        skill=skill,
        test_org=test_org,
        other=other,
        source="skills.api.update_skill",
    )


async def test_cross_tenant_delete_records_metric(auth_client, test_db_session, test_org):
    other = Organization(name="OtherDel", slug="other-org-del")
    test_db_session.add(other)
    await test_db_session.flush()
    skill = await _skill(test_db_session, test_org, org_id=other.id)

    resp = await auth_client.delete(f"/api/skills/{skill.id}")
    await _assert_cross_tenant_skill_404(
        resp=resp,
        test_db_session=test_db_session,
        skill=skill,
        test_org=test_org,
        other=other,
        source="skills.api.delete_skill",
    )


async def test_cross_tenant_apply_records_metric(auth_client, test_db_session, test_org):
    other = Organization(name="OtherApp", slug="other-org-app")
    test_db_session.add(other)
    await test_db_session.flush()
    skill = await _skill(test_db_session, test_org, org_id=other.id)

    resp = await auth_client.post(f"/api/skills/{skill.id}/apply")
    await _assert_cross_tenant_skill_404(
        resp=resp,
        test_db_session=test_db_session,
        skill=skill,
        test_org=test_org,
        other=other,
        source="skills.api.apply_skill",
    )


async def test_same_org_missing_skill_has_no_cross_tenant_metric(auth_client, test_db_session, test_org):
    missing_id = "00000000-0000-0000-0000-000000000001"
    for method, path, kwargs in [
        ("put", f"/api/skills/{missing_id}", {"json": {"name": "x"}}),
        ("delete", f"/api/skills/{missing_id}", {}),
        ("post", f"/api/skills/{missing_id}/transition", {"json": {"target": "under_review"}}),
        ("post", f"/api/skills/{missing_id}/apply", {}),
    ]:
        resp = await getattr(auth_client, method)(path, **kwargs)
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "Skill not found"

    rows = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        )
    ).scalars().all()
    assert not any(e.payload.get("resource_type") == "Skill" for e in rows)


async def test_transition_is_tenant_scoped(auth_client, test_db_session, test_org):
    other = Organization(name="Other", slug="other-org")
    test_db_session.add(other)
    await test_db_session.flush()
    skill = await _skill(test_db_session, test_org, org_id=other.id)

    resp = await auth_client.post(f"/api/skills/{skill.id}/transition", json={"target": "under_review"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Skill not found"

    rows = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        )
    ).scalars().all()
    assert any(
        e.payload.get("metric") == "cross_tenant_block"
        and e.payload.get("resource_type") == "Skill"
        and e.payload.get("requested_org_id") == test_org.id
        and e.payload.get("resource_org_id") == other.id
        and e.payload.get("skill_id") == skill.id
        and e.source == "skills.api.transition_skill"
        for e in rows
    )
