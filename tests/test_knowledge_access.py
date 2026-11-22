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
