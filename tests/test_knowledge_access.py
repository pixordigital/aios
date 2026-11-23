"""Permission-aware retrieval: strict tenant and classification filtering."""

from datetime import datetime, timedelta

from aios.governance.knowledge import (
    KnowledgeRecord,
    can_retrieve,
    fact_promotion_allowed,
    filter_retrievable,
    validate_provenance,
)


def _rec(**overrides):
    data = dict(
        org_id="t1", title="Meeting note", kind="statement",
        classification="internal", source_type="meeting", source_id="m1",
        derived_from=[], department_id=None,
    )
    data.update(overrides)
    return KnowledgeRecord(**data)


def test_cross_tenant_is_denied():
    ok, reason = can_retrieve(_rec(org_id="t2"), actor_org_id="t1", actor_departments={"sales"})
    assert not ok
    assert "tenant" in reason


def test_department_scope():
    rec = _rec(department_id="d1")
    assert can_retrieve(rec, actor_org_id="t1", actor_departments={"d1"})[0]
    assert not can_retrieve(rec, actor_org_id="t1", actor_departments={"d2"})[0]


def test_founder_and_restricted():
    rec = _rec(classification="restricted", department_id="d1")
    assert not can_retrieve(rec, actor_org_id="t1", actor_departments={"d1"})[0]
    assert can_retrieve(rec, actor_org_id="t1", actor_departments=set(), is_founder=True)[0]


def test_confidential_requires_explicit_grant():
    rec = _rec(classification="confidential", id="k1")
    assert not can_retrieve(rec, actor_org_id="t1", actor_departments={"d1"})[0]
    assert can_retrieve(rec, actor_org_id="t1", actor_departments=set(), granted_record_ids={"k1"})[0]


def test_deleted_and_expired_are_denied():
    now = datetime(2026, 11, 22)
    deleted = _rec(deleted_at=now)
    assert not can_retrieve(deleted, actor_org_id="t1", actor_departments=set(), now=now)[0]
    expired = _rec(retention_until=now - timedelta(days=1))
    assert not can_retrieve(expired, actor_org_id="t1", actor_departments=set(), now=now)[0]


def test_filter_returns_only_allowed():
    records = [
        _rec(id="a", org_id="t1"),
        _rec(id="b", org_id="t2"),
        _rec(id="c", classification="restricted"),
    ]
    kept = filter_retrievable(records, actor_org_id="t1", actor_departments=set())
    assert [r.id for r in kept] == ["a"]


def test_inference_must_cite_sources():
    assert "derived_from" in " ".join(validate_provenance(_rec(kind="inference")))
    assert validate_provenance(_rec(kind="inference", derived_from=["m1"])) == []
    assert validate_provenance(_rec(source_type="", derived_from=[]))


def test_statement_does_not_become_fact_silently():
    statement = _rec(kind="statement")
    assert not fact_promotion_allowed(statement, human_confirmed=False)
    assert fact_promotion_allowed(statement, human_confirmed=True)
    assert fact_promotion_allowed(_rec(kind="fact"), human_confirmed=False)


async def test_hybrid_search_defaults_to_permissioned_knowledge(monkeypatch):
    from aios.core import rag

    calls = {}

    async def fake_search(org_id, query, **kwargs):
        calls["org_id"] = org_id
        calls["query"] = query
        calls["kwargs"] = kwargs
        return [{"id": "k1"}]

    monkeypatch.setattr(rag, "search_knowledge_records", fake_search)
    out = await rag.hybrid_search("org1", "pricing", top_k=3)
    assert out == [{"id": "k1"}]
    assert calls["kwargs"]["actor_departments"] == set()
    assert calls["kwargs"]["is_founder"] is False
    assert calls["kwargs"]["granted_record_ids"] is None or calls["kwargs"]["granted_record_ids"] == set()


async def test_hybrid_search_no_legacy_memory_bypass_by_default(monkeypatch):
    from aios.core import rag

    async def fake_search(*args, **kwargs):
        return []

    monkeypatch.setattr(rag, "search_knowledge_records", fake_search)

    async def should_not_run(*args, **kwargs):
        raise AssertionError("legacy memory path should not run by default")

    monkeypatch.setattr("aios.core.memory._embed", should_not_run)
    out = await rag.hybrid_search("org1", "pricing", top_k=3)
    assert out == []


async def test_hybrid_search_has_no_unpermissioned_legacy_path():
    import inspect

    from aios.core import rag

    params = inspect.signature(rag.hybrid_search).parameters
    assert "include_legacy_memory" not in params
    assert "allow_legacy_unpermissioned" not in params
    assert "internal_caller" not in params


async def test_rag_search_tool_fails_closed_without_actor_context(monkeypatch):
    from aios.tools.rag_search import RagSearchTool

    async def fake_search(*args, **kwargs):
        raise AssertionError("search should not run when actor unresolved")

    monkeypatch.setattr("aios.core.rag.search_knowledge_records", fake_search)

    tool = RagSearchTool()
    tool._org_id = "org1"
    tool._agent_id = ""
    tool._actor_user_id = ""
    tool._actor_departments = set()
    tool._is_founder = False
    tool._granted_record_ids = set()

    out = await tool.run(query="pricing")
    assert out["ok"] is False
    assert out["fail_closed"] is True
    assert out["results"] == []
    assert out["count"] == 0
    assert out["source"] == "knowledge_records"
    assert "unresolved" in out["error"]
    assert out["actor_resolution"] == "none"
    assert "actor_user_id" in out["missing_actor_context"]
    assert "granted_record_ids" in out["missing_actor_context"]
    assert "fail-closed" in out["remediation"].lower()


async def test_rag_search_tool_allows_injected_actor_scope(monkeypatch):
    from aios.tools.rag_search import RagSearchTool

    captured = {}

    async def fake_search(org_id, query, **kwargs):
        captured["org_id"] = org_id
        captured["query"] = query
        captured["kwargs"] = kwargs
        return [{"id": "k1", "citation": {"record_id": "k1"}}]

    monkeypatch.setattr("aios.core.rag.search_knowledge_records", fake_search)

    tool = RagSearchTool()
    tool._org_id = "org1"
    tool._actor_departments = {"dept-sales"}
    tool._is_founder = False
    tool._granted_record_ids = set()

    out = await tool.run(query="pricing", top_k=3)
    assert out["ok"] is True
    assert out["count"] == 1
    assert out["actor_resolution"] == "injected"
    assert captured["kwargs"]["actor_departments"] == {"dept-sales"}
    assert captured["kwargs"]["is_founder"] is False


async def test_rag_search_honors_actor_resolved_scope_skips_db(monkeypatch):
    from aios.tools import rag_search

    async def boom_grants(*args, **kwargs):
        raise AssertionError("grant DB lookup should be skipped when scope resolved")

    class BoomSession:
        async def __aenter__(self):
            raise AssertionError("actor DB lookup should be skipped when scope resolved")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    captured = {}

    async def fake_search(org_id, query, **kwargs):
        captured.update(kwargs)
        return [{"id": "k1"}]

    monkeypatch.setattr(rag_search, "resolve_granted_record_ids", boom_grants)
    monkeypatch.setattr("aios.db.engine.async_session", lambda: BoomSession())
    monkeypatch.setattr("aios.core.rag.search_knowledge_records", fake_search)

    tool = rag_search.RagSearchTool()
    tool._org_id = "org1"
    tool._actor_user_id = "u1"
    tool._actor_departments = {"d1"}
    tool._is_founder = False
    tool._granted_record_ids = set()
    tool._actor_resolved = True

    out = await tool.run(query="pricing")
    assert out["ok"] is True
    assert out["actor_resolution"] == "injected"
    assert captured["actor_departments"] == {"d1"}
    assert captured["granted_record_ids"] == set()


async def test_rag_search_actor_resolved_user_only_still_resolves_scope(monkeypatch):
    from aios.tools import rag_search

    grant_calls = {"n": 0}

    async def fake_grants(org_id, actor_user_id):
        grant_calls["n"] += 1
        assert (org_id, actor_user_id) == ("org1", "u1")
        return {"kr-db"}

    captured = {}

    async def fake_search(org_id, query, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(rag_search, "resolve_granted_record_ids", fake_grants)
    monkeypatch.setattr("aios.core.rag.search_knowledge_records", fake_search)

    tool = rag_search.RagSearchTool()
    tool._org_id = "org1"
    tool._actor_user_id = "u1"
    tool._actor_departments = set()
    tool._is_founder = False
    tool._granted_record_ids = set()
    tool._actor_resolved = True  # resolved flag alone insufficient without scope

    out = await tool.run(query="pricing")
    assert out["ok"] is True
    assert grant_calls["n"] == 1
    assert captured["granted_record_ids"] == {"kr-db"}


async def test_tool_engine_injects_actor_identity_to_rag_tool(monkeypatch):
    from aios.core.tools import ToolEngine
    from aios.tools.rag_search import RagSearchTool

    captured = {}

    async def fake_run(self, query: str, top_k: int = 5):
        captured["org"] = getattr(self, "_org_id", "")
        captured["user"] = getattr(self, "_actor_user_id", "")
        captured["deps"] = set(getattr(self, "_actor_departments", set()))
        captured["founder"] = bool(getattr(self, "_is_founder", False))
        captured["grants"] = set(getattr(self, "_granted_record_ids", set()))
        return {"ok": True, "query": query, "results": [], "count": 0}

    monkeypatch.setattr(RagSearchTool, "run", fake_run)

    eng = ToolEngine(
        ["rag_search"],
        org_id="org1",
        agent_id="agent1",
        actor_user_id="user1",
        actor_departments={"d1"},
        is_founder=True,
        granted_record_ids={"k1"},
    )
    out = await eng.execute("rag_search", '{"query":"pricing"}')
    assert '"ok": true' in out.lower()
    assert captured == {
        "org": "org1",
        "user": "user1",
        "deps": {"d1"},
        "founder": True,
        "grants": {"k1"},
    }


async def test_search_knowledge_records_sql_acl_pushdown(test_db_session, test_org):
    from aios.core.rag import search_knowledge_records
    from aios.governance.knowledge import KnowledgeRecord

    rows = [
        ("open", "internal", None, "alpha"),
        ("dept", "internal", "d1", "alpha"),
        ("outside", "internal", "d2", "alpha"),
        ("secret", "confidential", None, "alpha"),
        ("locked", "restricted", None, "alpha"),
    ]
    records = [
        KnowledgeRecord(
            id=f"acl-{rid}", org_id=test_org.id, title=rid,
            kind="statement", classification=cls, department_id=dept,
            source_type="doc", source_id=rid, derived_from=[],
            search_text=text,
        )
        for rid, cls, dept, text in rows
    ]
    test_db_session.add_all(records)
    await test_db_session.commit()

    hits = await search_knowledge_records(
        test_org.id, "alpha", actor_departments={"d1"}, granted_record_ids={"acl-secret"}
    )
    ids = {h["record_id"] for h in hits}
    assert ids == {"acl-open", "acl-dept", "acl-secret"}

    hits = await search_knowledge_records(test_org.id, "alpha", actor_departments={"d1"})
    assert {h["record_id"] for h in hits} == {"acl-open", "acl-dept"}


async def test_search_knowledge_records_term_prefilter(test_db_session, test_org):
    from aios.core.rag import search_knowledge_records
    from aios.governance.knowledge import KnowledgeRecord

    for rid, text in (("match", "pricing rules"), ("other", "unrelated notes")):
        test_db_session.add(
            KnowledgeRecord(
                id=f"term-{rid}", org_id=test_org.id, title=rid,
                kind="statement", classification="internal",
                source_type="doc", source_id=rid, derived_from=[], search_text=text,
            )
        )
    await test_db_session.commit()

    hits = await search_knowledge_records(test_org.id, "pricing", is_founder=True)
    assert {h["record_id"] for h in hits} == {"term-match"}


async def test_resolve_granted_record_ids_requires_identity():
    from aios.tools.rag_search import resolve_granted_record_ids

    assert await resolve_granted_record_ids("", "u1") == set()
    assert await resolve_granted_record_ids("org1", "") == set()


async def test_resolve_granted_record_ids_active_only(test_db_session, test_org, test_user):
    from datetime import timedelta

    from aios.governance.knowledge import KnowledgeGrant, KnowledgeRecord, _now

    rec = KnowledgeRecord(
        id="kr-granted", org_id=test_org.id, title="Confidential",
        kind="statement", classification="confidential", source_type="doc",
        source_id="s1", derived_from=[], search_text="secret",
    )
    rec_revoked = KnowledgeRecord(
        id="kr-revoked", org_id=test_org.id, title="Revoked",
        kind="statement", classification="internal", source_type="doc",
        source_id="s2", derived_from=[], search_text="",
    )
    rec_expired = KnowledgeRecord(
        id="kr-expired", org_id=test_org.id, title="Expired",
        kind="statement", classification="internal", source_type="doc",
        source_id="s3", derived_from=[], search_text="",
    )
    test_db_session.add_all([rec, rec_revoked, rec_expired])
    active = KnowledgeGrant(org_id=test_org.id, user_id=test_user.id, record_id=rec.id)
    revoked = KnowledgeGrant(
        org_id=test_org.id, user_id=test_user.id, record_id=rec_revoked.id,
        revoked_at=_now(),
    )
    expired = KnowledgeGrant(
        org_id=test_org.id, user_id=test_user.id, record_id=rec_expired.id,
        expires_at=_now() - timedelta(days=1),
    )
    test_db_session.add_all([active, revoked, expired])
    await test_db_session.commit()

    from aios.tools.rag_search import resolve_granted_record_ids

    grants = await resolve_granted_record_ids(test_org.id, test_user.id)
    assert grants == {rec.id}


async def test_rag_search_resolves_db_grants_best_effort(monkeypatch):
    from aios.tools import rag_search

    async def fake_grants(org_id, actor_user_id):
        assert org_id == "org1"
        assert actor_user_id == "u1"
        return {"kr-db"}

    captured = {}

    async def fake_search(org_id, query, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(rag_search, "resolve_granted_record_ids", fake_grants)
    monkeypatch.setattr("aios.core.rag.search_knowledge_records", fake_search)

    tool = rag_search.RagSearchTool()
    tool._org_id = "org1"
    tool._actor_user_id = "u1"
    tool._actor_departments = set()
    tool._is_founder = False
    tool._granted_record_ids = set()

    out = await tool.run(query="pricing")
    assert out["ok"] is True
    assert captured["granted_record_ids"] == {"kr-db"}


async def test_rag_search_db_grant_resolution_error_fails_closed(monkeypatch):
    from aios.tools import rag_search

    async def boom(org_id, actor_user_id):
        raise RuntimeError("db boom")

    captured = {}

    async def fake_search(org_id, query, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(rag_search, "resolve_granted_record_ids", boom)
    monkeypatch.setattr("aios.core.rag.search_knowledge_records", fake_search)

    tool = rag_search.RagSearchTool()
    tool._org_id = "org1"
    tool._actor_user_id = "u1"
    tool._actor_departments = {"d1"}
    tool._is_founder = False
    tool._granted_record_ids = set()

    out = await tool.run(query="pricing")
    assert out["ok"] is True
    assert captured["granted_record_ids"] == set()


async def test_knowledge_records_pagination(auth_client):
    for i in range(3):
        resp = await auth_client.post(
            "/api/knowledge/records",
            json={"title": f"Rec {i}", "kind": "statement", "classification": "internal", "source_type": "test"},
        )
        assert resp.status_code == 200, resp.text

    resp = await auth_client.get("/api/knowledge/records", params={"limit": 2, "offset": 0})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert body["total_scanned_visible"] == 3
    assert body["total_exact"] is True
    assert body["total_note"] == "total is exact visible count"
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["items"]) == 2
    assert body["scanned"] == 3
    assert body["scan_limit"] == 2000
    assert body["truncated"] is False

    resp2 = await auth_client.get("/api/knowledge/records", params={"limit": 2, "offset": 2})
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["total"] == 3
    assert body2["total_scanned_visible"] == 3
    assert body2["total_exact"] is True
    assert len(body2["items"]) == 1
    assert body2["truncated"] is False


async def test_knowledge_records_scan_truncation_metadata(auth_client, monkeypatch):
    import aios.api.knowledge as knowledge_api

    monkeypatch.setattr(knowledge_api, "KNOWLEDGE_RECORD_SCAN_LIMIT", 2)
    for i in range(3):
        resp = await auth_client.post(
            "/api/knowledge/records",
            json={"title": f"ScanRec {i}", "kind": "statement", "classification": "internal", "source_type": "test"},
        )
        assert resp.status_code == 200, resp.text

    resp = await auth_client.get("/api/knowledge/records", params={"limit": 10, "offset": 0})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] == 2
    assert body["scan_limit"] == 2
    assert body["truncated"] is True
    # Compat total = visible count within scanned set; additive fields make ambiguity explicit.
    assert body["total"] == len(body["items"])
    assert body["total_scanned_visible"] == len(body["items"])
    assert body["total_exact"] is False
    assert body["total_note"] == "total is visible count within scanned set; scan truncated, true total unknown"
    assert body["total"] <= 2


async def test_knowledge_records_limit_cap(auth_client):
    resp = await auth_client.get("/api/knowledge/records", params={"limit": 201})
    assert resp.status_code == 422
    resp = await auth_client.get("/api/knowledge/records", params={"limit": 0})
    assert resp.status_code == 422
    resp = await auth_client.get("/api/knowledge/records", params={"offset": -1})
    assert resp.status_code == 422


async def test_knowledge_search_limit_bounded(auth_client):
    resp = await auth_client.get("/api/knowledge/search", params={"q": "x", "top_k": 51})
    assert resp.status_code == 422
    resp = await auth_client.get("/api/knowledge/search", params={"q": "x", "top_k": 0})
    assert resp.status_code == 422


async def test_cross_tenant_knowledge_record_access_records_metric(auth_client, test_db_session, second_org):
    from sqlalchemy import select
    from aios.governance.security import SecurityEvent

    other = KnowledgeRecord(
        org_id=second_org.id,
        title="Other org secret",
        kind="statement",
        classification="internal",
        source_type="test",
        source_id="s1",
    )
    test_db_session.add(other)
    await test_db_session.commit()
    await test_db_session.refresh(other)

    cases = [
        ("post", f"/api/knowledge/records/{other.id}/promote", {"human_confirmed": True}, "knowledge.api.promote"),
        ("post", f"/api/knowledge/records/{other.id}/soft-delete", None, "knowledge.api.soft_delete"),
        ("get", f"/api/knowledge/records/{other.id}/delete-eligibility", None, "knowledge.api.delete_eligibility"),
    ]
    for method, path, body, source in cases:
        req = getattr(auth_client, method)
        resp = await req(path, json=body) if body is not None else await req(path)
        assert resp.status_code == 404, (path, resp.text)

    rows = (
        await test_db_session.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == "security.cross_tenant.blocked")
        )
    ).scalars().all()
    for _, _, _, source in cases:
        assert any(
            e.payload.get("metric") == "cross_tenant_block"
            and e.payload.get("resource_type") == "KnowledgeRecord"
            and e.payload.get("resource_org_id") == second_org.id
            and e.payload.get("record_id") == other.id
            and e.source == source
            for e in rows
        ), source
