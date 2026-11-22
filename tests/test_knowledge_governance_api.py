"""Knowledge governance API: provenance, permission-aware retrieval, promotion, deletion."""

from aios.db.models import Organization
from aios.governance.knowledge import KnowledgeRecord
from aios.governance.ocp import Department, DepartmentMember


async def _create(auth_client, title, **extra):
    body = {
        "title": title,
        "content": "text",
        "kind": "statement",
        "classification": "internal",
        "source_type": "meeting",
        **extra,
    }
    resp = await auth_client.post("/api/knowledge/records", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def test_create_provenance_and_promotion(auth_client):
    resp = await auth_client.post(
        "/api/knowledge/records",
        json={"title": "Inference", "kind": "inference", "source_type": "meeting"},
    )
    assert resp.status_code == 400
    assert "derived_from" in resp.text

    rid = await _create(auth_client, "Claim")
    resp = await auth_client.post(f"/api/knowledge/records/{rid}/promote", json={})
    assert resp.status_code == 400  # no human confirmation

    resp = await auth_client.post(
        f"/api/knowledge/records/{rid}/promote", json={"human_confirmed": True}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["kind"] == "fact"


async def test_permission_aware_listing(auth_client, test_db_session, test_org, test_user):
    dept = Department(org_id=test_org.id, name="Sales", slug="sales-knowledge")
    test_db_session.add(dept)
    await test_db_session.flush()

    plain = await _create(auth_client, "Plain")
    restricted = await _create(auth_client, "Restricted", classification="restricted")
    confidential = await _create(auth_client, "Confidential", classification="confidential")
    dept_only = await _create(auth_client, "Dept", department_id=dept.id)

    titles = {r["title"] for r in (await auth_client.get("/api/knowledge/records")).json()["items"]}
    assert "Plain" in titles
    assert "Restricted" not in titles
    assert "Confidential" not in titles
    assert "Dept" not in titles

    test_db_session.add(
        DepartmentMember(
            org_id=test_org.id, department_id=dept.id, member_type="human", user_id=test_user.id
        )
    )
    await test_db_session.commit()
    titles = {r["title"] for r in (await auth_client.get("/api/knowledge/records")).json()["items"]}
    assert "Dept" in titles

    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()
    titles = {r["title"] for r in (await auth_client.get("/api/knowledge/records")).json()["items"]}
    assert {"Plain", "Restricted", "Confidential", "Dept"} <= titles


async def test_soft_delete_requires_founder(auth_client, test_db_session, test_org, test_user):
    rid = await _create(auth_client, "Doomed")
    resp = await auth_client.post(f"/api/knowledge/records/{rid}/soft-delete")
    assert resp.status_code == 403

    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()
    resp = await auth_client.post(f"/api/knowledge/records/{rid}/soft-delete")
    assert resp.status_code == 200, resp.text
    titles = {r["title"] for r in (await auth_client.get("/api/knowledge/records")).json()["items"]}
    assert "Doomed" not in titles


async def test_records_are_tenant_scoped(auth_client, test_db_session):
    other = Organization(name="Other", slug="other-knowledge-org")
    test_db_session.add(other)
    await test_db_session.flush()
    secret = KnowledgeRecord(org_id=other.id, title="Secret record", source_type="meeting")
    test_db_session.add(secret)
    await test_db_session.commit()

    titles = {r["title"] for r in (await auth_client.get("/api/knowledge/records")).json()["items"]}
    assert "Secret record" not in titles
    resp = await auth_client.post(f"/api/knowledge/records/{secret.id}/promote", json={"human_confirmed": True})
    assert resp.status_code == 404
