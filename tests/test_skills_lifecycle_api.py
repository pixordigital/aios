"""Skills lifecycle API: state ladder enforced, Founder gate for publish/deprecate."""

from aios.db.models import Agent, Organization, Skill


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


async def test_transition_is_tenant_scoped(auth_client, test_db_session, test_org):
    other = Organization(name="Other", slug="other-org")
    test_db_session.add(other)
    await test_db_session.flush()
    skill = await _skill(test_db_session, test_org, org_id=other.id)

    resp = await auth_client.post(f"/api/skills/{skill.id}/transition", json={"target": "under_review"})
    assert resp.status_code == 404
