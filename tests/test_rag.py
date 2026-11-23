"""RAG guardrails - observability for full-org KnowledgeRecord scans."""

import pytest

from aios.core import rag
from aios.governance.knowledge import KnowledgeRecord


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *args, **kwargs):
        return _FakeResult(self._rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_rows(n, org_id="org1"):
    return [
        KnowledgeRecord(
            id=f"kr-{i}",
            org_id=org_id,
            title=f"Pricing doc {i}",
            content="pricing plan details",
            kind="fact",
            classification="internal",
            source_type="doc",
            source_id=f"s-{i}",
            derived_from=[],
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_search_knowledge_records_warns_on_large_scan(monkeypatch):
    rows = _make_rows(3)
    monkeypatch.setattr(rag, "async_session", lambda: _FakeSession(rows))
    monkeypatch.setattr(rag, "RAG_SCAN_WARN_THRESHOLD", 2)
    warnings = []

    def fake_warning(msg, *args, **kwargs):
        warnings.append(msg % args if args else msg)

    monkeypatch.setattr(rag.logger, "warning", fake_warning)

    hits = await rag.search_knowledge_records("org1", "pricing", top_k=5)

    assert isinstance(hits, list)
    assert any("full-org scan exceeded threshold" in m for m in warnings)
    assert any("org=org1" in m and "scanned=3" in m and "threshold=2" in m for m in warnings)


@pytest.mark.asyncio
async def test_search_knowledge_records_vector_candidates_rechecked(monkeypatch):
    monkeypatch.setattr(rag, "async_session", lambda: _FakeSession(_make_rows(1)))

    def mk(rid, org, classification):
        return KnowledgeRecord(
            id=rid, org_id=org, title=rid, content="pricing",
            kind="fact", classification=classification, source_type="doc",
            source_id=rid, derived_from=[],
        )

    candidates = [
        (mk("vk-ok", "org1", "internal"), 0.9),
        (mk("vk-secret", "org1", "confidential"), 0.8),
        (mk("vk-tenant", "org2", "internal"), 0.7),
    ]

    async def fake_vector(org_id, query, conditions, top_k):
        return candidates

    monkeypatch.setattr(rag, "_vector_candidates", fake_vector)
    hits = await rag.search_knowledge_records("org1", "pricing", top_k=10)
    ids = {h["record_id"] for h in hits}
    assert "vk-ok" in ids
    assert "vk-secret" not in ids
    assert "vk-tenant" not in ids


@pytest.mark.asyncio
async def test_store_knowledge_vectors_upserts_when_enabled(monkeypatch):
    calls = []

    class _WriteSession:
        async def execute(self, sql, params=None):
            calls.append((str(sql), params))

        async def commit(self):
            calls.append(("commit", None))

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setitem(rag.RAG_STATUS, "vector", True)
    monkeypatch.setitem(rag.RAG_STATUS, "knowledge_hnsw", True)
    monkeypatch.setattr("aios.core.vector_store.use_postgres", lambda: True)
    monkeypatch.setattr(rag, "async_session", lambda: _WriteSession())

    record = _make_rows(1)[0]
    stored = await rag.store_knowledge_vectors([record], [[0.1, 0.2]])
    assert stored == 1
    assert any("ON CONFLICT" in sql for sql, _ in calls if isinstance(sql, str))
    assert calls[0][1]["emb"] == "[0.1000000,0.2000000]"


@pytest.mark.asyncio
async def test_search_knowledge_records_no_warn_below_threshold(monkeypatch):
    rows = _make_rows(2)
    monkeypatch.setattr(rag, "async_session", lambda: _FakeSession(rows))
    monkeypatch.setattr(rag, "RAG_SCAN_WARN_THRESHOLD", 5)
    warnings = []

    def fake_warning(msg, *args, **kwargs):
        warnings.append(msg % args if args else msg)

    monkeypatch.setattr(rag.logger, "warning", fake_warning)

    hits = await rag.search_knowledge_records("org1", "pricing", top_k=5)

    assert isinstance(hits, list)
    assert not any("full-org scan exceeded threshold" in m for m in warnings)
