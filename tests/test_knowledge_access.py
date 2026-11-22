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


async def test_hybrid_search_legacy_escape_hatch_requires_internal_flags(monkeypatch):
    from aios.core import rag

    async def fake_search(*args, **kwargs):
        return []

    monkeypatch.setattr(rag, "search_knowledge_records", fake_search)

    async def should_not_run(*args, **kwargs):
        raise AssertionError("legacy memory path must stay blocked without all internal flags")

    monkeypatch.setattr("aios.core.memory._embed", should_not_run)

    # Single flag insufficient
    out = await rag.hybrid_search("org1", "pricing", include_legacy_memory=True)
    assert out == []
    out = await rag.hybrid_search(
        "org1", "pricing", include_legacy_memory=True, allow_legacy_unpermissioned=True
    )
    assert out == []


async def test_hybrid_search_legacy_escape_hatch_all_internal_flags(monkeypatch):
    from aios.core import rag

    async def fake_search(*args, **kwargs):
        return []

    monkeypatch.setattr(rag, "search_knowledge_records", fake_search)

    class _FakeResult:
        def __iter__(self):
            return iter([("m1", "legacy content", "[0.1]")])

    class _FakeSession:
        async def execute(self, *args, **kwargs):
            return _FakeResult()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("aios.core.rag.async_session", lambda: _FakeSession())
    monkeypatch.setattr("aios.core.memory._embed", lambda q: [0.1])

    out = await rag.hybrid_search(
        "org1",
        "pricing",
        include_legacy_memory=True,
        allow_legacy_unpermissioned=True,
        internal_caller=True,
    )
    assert len(out) == 1
    assert out[0]["source"] == "legacy_memory"
    assert out[0]["legacy_unpermissioned"] is True


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


async def test_tool_engine_injects_actor_identity_to_rag_tool(monkeypatch):
    from aios.core.tools import ToolEngine
    from aios.tools.rag_search import RagSearchTool

    captured = {}

    async def fake_run(self, query: str, top_k: int = 5):
        captured["org"] = getattr(self, "_org_id", "")
        captured["user"] = getattr(self, "_actor_user_id", "")
        captured["deps"] = set(getattr(self, "_actor_departments", set()))
        captured["founder"] = bool(getattr(self, "_is_founder", False))
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
    }
