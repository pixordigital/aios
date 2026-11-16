"""Vector store selection: Postgres in production, SQLite in dev."""

import json

import pytest

from aios.config import settings
from aios.core import vector_store


def test_backend_switch_overrides_dialect(monkeypatch):
    monkeypatch.setattr(settings, "vector_backend", "sqlite")
    assert vector_store.use_postgres() is False
    monkeypatch.setattr(settings, "vector_backend", "postgres")
    assert vector_store.use_postgres() is True


def test_auto_follows_dialect(monkeypatch):
    import aios.db.engine as db_engine

    class _Dialect:
        name = "sqlite"

    class _Engine:
        dialect = _Dialect()

    monkeypatch.setattr(settings, "vector_backend", "auto")
    monkeypatch.setattr(db_engine, "engine", _Engine())
    assert vector_store.use_postgres() is False

    _Engine.dialect.name = "postgresql"
    assert vector_store.use_postgres() is True


@pytest.mark.asyncio(loop_scope="function")
async def test_sqlite_write_does_not_call_pg_store(tmp_path, monkeypatch):
    from aios.core.memory import MemoryManager

    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "vector_backend", "sqlite")

    async def _boom(*a, **kw):
        raise AssertionError("pg store used on sqlite backend")

    monkeypatch.setattr(vector_store, "store", _boom)
    mgr = MemoryManager("vector-store-sqlite-agent")
    await mgr._store_vector("customer prefers morning callbacks")
    assert await mgr.search_similar("morning callbacks", top_k=1)


def test_migration_literal_round_trip():
    from scripts.migrate_vectors_to_pg import _vec_literal

    emb = json.dumps([0.5] * 384)
    literal = _vec_literal(emb)
    assert literal and literal.startswith("[") and literal.count(",") == 383
    assert _vec_literal(json.dumps([0.5] * 1536)) is None
