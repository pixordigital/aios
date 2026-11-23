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


async def test_grant_create_use_and_revoke(auth_client, test_db_session, test_org, test_user):
    resp = await auth_client.post(
        "/api/knowledge/grants", json={"record_id": "r1", "user_id": test_user.id}
    )
    assert resp.status_code == 403  # non-founder blocked

    test_org.extra_data = {"founder_user_id": test_user.id}
    rid = await _create(auth_client, "Secret", classification="confidential")
    resp = await auth_client.post(
        "/api/knowledge/grants", json={"record_id": rid, "user_id": test_user.id}
    )
    assert resp.status_code == 200, resp.text
    gid = resp.json()["id"]

    from aios.tools.rag_search import resolve_granted_record_ids

    assert await resolve_granted_record_ids(test_org.id, test_user.id) == {rid}

    missing = await auth_client.post(
        "/api/knowledge/grants", json={"record_id": "missing", "user_id": test_user.id}
    )
    assert missing.status_code == 404

    resp = await auth_client.post(f"/api/knowledge/grants/{gid}/revoke")
    assert resp.status_code == 200 and resp.json()["revoked_at"]
    assert await resolve_granted_record_ids(test_org.id, test_user.id) == set()

    bad = await auth_client.post(
        "/api/knowledge/grants",
        json={"record_id": rid, "user_id": test_user.id, "expires_at": "not-a-date"},
    )
    assert bad.status_code == 400

    rid_expired = await _create(auth_client, "Expired secret", classification="confidential")
    expired = await auth_client.post(
        "/api/knowledge/grants",
        json={
            "record_id": rid_expired,
            "user_id": test_user.id,
            "expires_at": "2020-01-01T00:00:00+00:00",
        },
    )
    assert expired.status_code == 200, expired.text
    assert await resolve_granted_record_ids(test_org.id, test_user.id) == set()

    rid_future = await _create(auth_client, "Future secret", classification="confidential")
    future = await auth_client.post(
        "/api/knowledge/grants",
        json={
            "record_id": rid_future,
            "user_id": test_user.id,
            "expires_at": "2099-01-01T00:00:00Z",
        },
    )
    assert future.status_code == 200, future.text
    assert await resolve_granted_record_ids(test_org.id, test_user.id) == {rid_future}


async def test_granted_confidential_visible_in_list_and_search(
    auth_client, test_db_session, test_org, test_user
):
    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()

    rid = await _create(
        auth_client,
        "Granted confidential pricing",
        content="pricing confidential zebra",
        classification="confidential",
    )
    # Founder sees it; remove founder to prove grant path.
    test_org.extra_data = {}
    await test_db_session.commit()

    titles = {r["title"] for r in (await auth_client.get("/api/knowledge/records")).json()["items"]}
    assert "Granted confidential pricing" not in titles
    resp = await auth_client.get("/api/knowledge/search", params={"q": "pricing confidential zebra"})
    assert resp.status_code == 200, resp.text
    assert all(r["title"] != "Granted confidential pricing" for r in resp.json()["results"])

    # Re-grant as founder.
    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()
    grant_resp = await auth_client.post(
        "/api/knowledge/grants", json={"record_id": rid, "user_id": test_user.id}
    )
    assert grant_resp.status_code == 200, grant_resp.text
    gid = grant_resp.json()["id"]

    test_org.extra_data = {}
    await test_db_session.commit()

    titles = {r["title"] for r in (await auth_client.get("/api/knowledge/records")).json()["items"]}
    assert "Granted confidential pricing" in titles
    resp = await auth_client.get("/api/knowledge/search", params={"q": "pricing confidential zebra"})
    assert resp.status_code == 200, resp.text
    search_titles = {r["title"] for r in resp.json()["results"]}
    assert "Granted confidential pricing" in search_titles

    # Revoke: fail-closed visibility removed.
    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()
    revoke_resp = await auth_client.post(f"/api/knowledge/grants/{gid}/revoke")
    assert revoke_resp.status_code == 200, revoke_resp.text

    test_org.extra_data = {}
    await test_db_session.commit()
    titles = {r["title"] for r in (await auth_client.get("/api/knowledge/records")).json()["items"]}
    assert "Granted confidential pricing" not in titles
    resp = await auth_client.get("/api/knowledge/search", params={"q": "pricing confidential zebra"})
    assert resp.status_code == 200, resp.text
    assert all(r["title"] != "Granted confidential pricing" for r in resp.json()["results"])


async def test_grant_resolution_error_fails_closed_in_list_and_search(
    auth_client, test_db_session, test_org, test_user, monkeypatch
):
    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()
    await _create(
        auth_client,
        "Confidential but resolver broken",
        content="resolver broken zebra",
        classification="confidential",
    )
    test_org.extra_data = {}
    await test_db_session.commit()

    import aios.tools.rag_search as rag_search

    async def boom(*_args, **_kwargs):
        raise RuntimeError("grant resolver down")

    monkeypatch.setattr(rag_search, "resolve_granted_record_ids", boom)

    titles = {r["title"] for r in (await auth_client.get("/api/knowledge/records")).json()["items"]}
    assert "Confidential but resolver broken" not in titles

    resp = await auth_client.get("/api/knowledge/search", params={"q": "resolver broken zebra"})
    assert resp.status_code == 200, resp.text
    assert all(r["title"] != "Confidential but resolver broken" for r in resp.json()["results"])


async def test_ingest_chunks_are_bounded_and_cited(auth_client, test_db_session, test_org, test_user):
    resp = await auth_client.post("/api/knowledge/ingest", json={"title": "Doc", "content": "x", "source_type": "doc"})
    assert resp.status_code == 403  # founder gate

    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()
    resp = await auth_client.post(
        "/api/knowledge/ingest",
        json={
            "title": "Policy",
            "content": " ".join(["alpha"] * 120),
            "source_type": "doc",
            "source_id": "policy-1",
            "chunk_size": 200,
            "classification": "internal",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] >= 2
    for chunk in body["chunks"]:
        citation = chunk["citation"]
        assert citation["source_type"] == "doc"
        assert citation["source_id"] == "policy-1"
        assert citation["provenance"]["ingestion"] == "document_chunk"
        assert citation["provenance"]["chunk_count"] == body["count"]

    resp = await auth_client.get("/api/knowledge/search", params={"q": "alpha"})
    hits = resp.json()["results"]
    assert hits and all("citation" in hit for hit in hits)
    assert any(hit["citation"]["provenance"].get("ingestion") == "document_chunk" for hit in hits)

    oversized = await auth_client.post(
        "/api/knowledge/ingest",
        json={
            "title": "Big",
            "content": " ".join(["word"] * 400),
            "source_type": "doc",
            "chunk_size": 200,
            "max_chunks": 2,
        },
    )
    assert oversized.status_code == 413


async def test_search_permission_filtering_and_citations(auth_client, test_db_session, test_org, test_user):
    dept = Department(org_id=test_org.id, name="Sales", slug="sales-search")
    test_db_session.add(dept)
    await test_db_session.flush()

    await _create(auth_client, "Public pricing policy", content="pricing table alfa", classification="internal")
    await _create(auth_client, "Secret legal", content="pricing table beta", classification="restricted")
    await _create(auth_client, "Confidential deal", content="pricing table gamma", classification="confidential")
    await _create(auth_client, "Dept playbook", content="pricing table delta", classification="internal", department_id=dept.id)

    resp = await auth_client.get("/api/knowledge/search", params={"q": "pricing"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "knowledge_records"
    titles = {r["title"] for r in body["results"]}
    assert "Public pricing policy" in titles
    assert "Secret legal" not in titles
    assert "Confidential deal" not in titles
    assert "Dept playbook" not in titles
    hit = next(r for r in body["results"] if r["title"] == "Public pricing policy")
    assert hit["source_type"] == "meeting"
    assert hit["citation"]["record_id"] == hit["id"]
    assert hit["citation"]["source_type"] == "meeting"
    assert "provenance" in hit["citation"]

    test_db_session.add(
        DepartmentMember(org_id=test_org.id, department_id=dept.id, member_type="human", user_id=test_user.id)
    )
    await test_db_session.commit()
    titles = {r["title"] for r in (await auth_client.get("/api/knowledge/search", params={"q": "pricing"})).json()["results"]}
    assert "Dept playbook" in titles

    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()
    titles = {r["title"] for r in (await auth_client.get("/api/knowledge/search", params={"q": "pricing"})).json()["results"]}
    assert {"Public pricing policy", "Secret legal", "Confidential deal", "Dept playbook"} <= titles


async def test_search_is_tenant_scoped(auth_client, test_db_session, test_org):
    other = Organization(name="Other", slug="other-search-org")
    test_db_session.add(other)
    await test_db_session.flush()
    secret = KnowledgeRecord(
        org_id=other.id,
        title="Other tenant pricing",
        content="pricing secret",
        kind="statement",
        classification="internal",
        source_type="meeting",
        source_id="m1",
    )
    test_db_session.add(secret)
    await _create(auth_client, "My pricing", content="pricing mine")
    await test_db_session.commit()

    resp = await auth_client.get("/api/knowledge/search", params={"q": "pricing"})
    assert resp.status_code == 200, resp.text
    titles = {r["title"] for r in resp.json()["results"]}
    assert "My pricing" in titles
    assert "Other tenant pricing" not in titles
