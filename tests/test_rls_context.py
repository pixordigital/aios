"""Optional Postgres RLS org-context wiring. Fail-safe defaults."""

import pytest
from sqlalchemy import text

from aios.db.rls import (
    apply_rls_org_context,
    bind_session_rls,
    get_rls_org_id,
    reset_rls_org_id,
    rls_context_enabled,
    set_rls_org_id,
)


class _FakeDialect:
    def __init__(self, name: str):
        self.name = name


class _FakeBind:
    def __init__(self, dialect_name: str):
        self.dialect = _FakeDialect(dialect_name)


class _FakeSession:
    def __init__(self, dialect_name: str = "sqlite"):
        self._bind = _FakeBind(dialect_name)
        self.calls: list[tuple[object, dict | None]] = []

    def get_bind(self):
        return self._bind

    async def execute(self, stmt, params=None):
        self.calls.append((stmt, params))
        return None


@pytest.mark.asyncio
async def test_rls_noop_when_disabled(monkeypatch):
    import aios.db.rls as rls

    monkeypatch.setattr(rls.settings, "rls_context_enabled", False)
    session = _FakeSession("postgresql")
    token = set_rls_org_id("org-1")
    try:
        applied = await apply_rls_org_context(session)
    finally:
        reset_rls_org_id(token)
    assert applied is False
    assert session.calls == []


@pytest.mark.asyncio
async def test_rls_noop_on_sqlite_even_when_enabled(monkeypatch):
    import aios.db.rls as rls

    monkeypatch.setattr(rls.settings, "rls_context_enabled", True)
    session = _FakeSession("sqlite")
    token = set_rls_org_id("org-1")
    try:
        applied = await apply_rls_org_context(session)
    finally:
        reset_rls_org_id(token)
    assert applied is False
    assert session.calls == []


@pytest.mark.asyncio
async def test_rls_noop_when_org_missing(monkeypatch):
    import aios.db.rls as rls

    monkeypatch.setattr(rls.settings, "rls_context_enabled", True)
    session = _FakeSession("postgresql")
    # no contextvar org, no explicit org
    token = set_rls_org_id(None)
    try:
        applied = await apply_rls_org_context(session)
    finally:
        reset_rls_org_id(token)
    assert applied is False
    assert session.calls == []


@pytest.mark.asyncio
async def test_rls_applies_set_config_on_postgres(monkeypatch):
    import aios.db.rls as rls

    monkeypatch.setattr(rls.settings, "rls_context_enabled", True)
    session = _FakeSession("postgresql")
    token = set_rls_org_id("org-123")
    try:
        applied = await apply_rls_org_context(session)
    finally:
        reset_rls_org_id(token)
    assert applied is True
    assert len(session.calls) == 1
    stmt, params = session.calls[0]
    assert "set_config('app.current_org_id'" in str(stmt)
    assert params == {"org_id": "org-123"}


@pytest.mark.asyncio
async def test_rls_explicit_org_overrides_contextvar(monkeypatch):
    import aios.db.rls as rls

    monkeypatch.setattr(rls.settings, "rls_context_enabled", True)
    session = _FakeSession("postgresql")
    token = set_rls_org_id("org-context")
    try:
        applied = await apply_rls_org_context(session, org_id="org-explicit")
    finally:
        reset_rls_org_id(token)
    assert applied is True
    assert session.calls[0][1] == {"org_id": "org-explicit"}


@pytest.mark.asyncio
async def test_sqlalchemy_backend_applies_rls_once(monkeypatch):
    import aios.db.rls as rls
    from aios.db.backends.sqlalchemy_backend import SQLAlchemyBackend

    monkeypatch.setattr(rls.settings, "rls_context_enabled", True)
    session = _FakeSession("postgresql")
    token = set_rls_org_id("org-abc")
    try:
        backend = SQLAlchemyBackend(session=session)
        await backend.execute(text("SELECT 1"))
        await backend.execute(text("SELECT 2"))
    finally:
        reset_rls_org_id(token)

    # first call is set_config, rest are actual queries
    assert len(session.calls) == 3
    assert "set_config('app.current_org_id'" in str(session.calls[0][0])
    assert session.calls[0][1] == {"org_id": "org-abc"}
    assert str(session.calls[1][0]) == "SELECT 1"
    assert str(session.calls[2][0]) == "SELECT 2"


@pytest.mark.asyncio
async def test_sqlalchemy_backend_noop_on_sqlite(monkeypatch):
    import aios.db.rls as rls
    from aios.db.backends.sqlalchemy_backend import SQLAlchemyBackend

    monkeypatch.setattr(rls.settings, "rls_context_enabled", True)
    session = _FakeSession("sqlite")
    token = set_rls_org_id("org-abc")
    try:
        backend = SQLAlchemyBackend(session=session)
        await backend.execute(text("SELECT 1"))
    finally:
        reset_rls_org_id(token)

    assert len(session.calls) == 1
    assert str(session.calls[0][0]) == "SELECT 1"


@pytest.mark.asyncio
async def test_bind_session_rls_sets_and_applies(monkeypatch):
    import aios.db.rls as rls

    monkeypatch.setattr(rls.settings, "rls_context_enabled", True)
    session = _FakeSession("postgresql")
    token = await bind_session_rls(session, "org-job")
    try:
        assert get_rls_org_id() == "org-job"
        assert len(session.calls) == 1
        assert "set_config('app.current_org_id'" in str(session.calls[0][0])
        assert session.calls[0][1] == {"org_id": "org-job"}
    finally:
        if token is not None:
            reset_rls_org_id(token)
    assert get_rls_org_id() is None


@pytest.mark.asyncio
async def test_sqlalchemy_backend_bind_org_applies(monkeypatch):
    import aios.db.rls as rls
    from aios.db.backends.sqlalchemy_backend import SQLAlchemyBackend

    monkeypatch.setattr(rls.settings, "rls_context_enabled", True)
    session = _FakeSession("postgresql")
    backend = SQLAlchemyBackend(session=session)
    applied = await backend.bind_org("org-bound")
    assert applied is True
    await backend.execute(text("SELECT 1"))
    assert len(session.calls) == 2
    assert session.calls[0][1] == {"org_id": "org-bound"}
    assert str(session.calls[1][0]) == "SELECT 1"
