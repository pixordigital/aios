"""Actor context wiring for MCP/tools API endpoints.

Fail-closed must remain when identity unresolvable; authenticated callers get
best-effort actor context so rag_search/knowledge tools can authorize.
"""

import pytest


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, org=None, depts=None):
        self.org = org
        self.depts = list(depts or [])

    async def execute(self, _q):
        return _ScalarResult(self.depts)

    async def get(self, _model, _id):
        return self.org


class _FakeUser:
    id = "u1"
    org_id = "org1"
    role = "admin"


class _FakeOrg:
    id = "org1"
    extra_data = {}


@pytest.mark.asyncio
async def test_mcp_call_wires_actor_context(monkeypatch):
    from aios.api import mcp as mcp_api

    captured = {}

    class _FakeToolEngine:
        def __init__(self, names, **kwargs):
            captured["names"] = names
            captured["kwargs"] = kwargs

        async def execute(self, name, args_json):
            captured["exec"] = (name, args_json)
            return '{"ok":true}'

    class _FakeTool:
        name = "rag_search"
        code_reference = ""

    monkeypatch.setattr("aios.core.tools.ToolEngine", _FakeToolEngine)
    monkeypatch.setattr(mcp_api, "_tool_actor_context", lambda db, user: _coro({
        "actor_user_id": "u1",
        "actor_departments": {"dept-a"},
        "is_founder": False,
        "granted_record_ids": set(),
    }))

    async def _fake_exec(*args, **kwargs):
        return _ScalarResult([_FakeTool()])

    db = _FakeDB()
    db.execute = _fake_exec
    out = await mcp_api.mcp_call(
        {"name": "rag_search", "arguments": {"query": "pricing"}},
        db=db,
        org_id="org1",
        user=_FakeUser(),
    )
    assert out["ok"] is True
    assert captured["kwargs"]["org_id"] == "org1"
    assert captured["kwargs"]["actor_user_id"] == "u1"
    assert captured["kwargs"]["actor_departments"] == {"dept-a"}
    assert captured["kwargs"]["is_founder"] is False
    assert captured["kwargs"]["granted_record_ids"] == set()


@pytest.mark.asyncio
async def test_tools_test_endpoint_wires_actor_context(monkeypatch):
    from aios.api import tools as tools_api

    captured = {}

    class _FakeToolEngine:
        def __init__(self, names, **kwargs):
            captured["names"] = names
            captured["kwargs"] = kwargs

        async def execute(self, name, args_json):
            return '{"ok":true}'

    class _FakeTool:
        id = "t1"
        org_id = "org1"
        name = "rag_search"
        code_reference = ""

    monkeypatch.setattr(tools_api, "ToolEngine", _FakeToolEngine)
    monkeypatch.setattr("aios.core.tools.ToolEngine", _FakeToolEngine)
    monkeypatch.setattr(tools_api, "_tool_actor_context", lambda db, user: _coro({
        "actor_user_id": "u1",
        "actor_departments": {"dept-a"},
        "is_founder": True,
        "granted_record_ids": {"kr1"},
    }))

    db = _FakeDB()
    db.get = lambda _m, _id: _coro(_FakeTool())
    out = await tools_api.test_tool(
        "t1",
        {"arguments": {"query": "pricing"}},
        db=db,
        org_id="org1",
        user=_FakeUser(),
    )
    assert out["ok"] is True
    assert captured["kwargs"]["org_id"] == "org1"
    assert captured["kwargs"]["actor_user_id"] == "u1"
    assert captured["kwargs"]["actor_departments"] == {"dept-a"}
    assert captured["kwargs"]["is_founder"] is True
    assert captured["kwargs"]["granted_record_ids"] == {"kr1"}


@pytest.mark.asyncio
async def test_tool_actor_context_best_effort_from_user_and_org():
    from aios.api.tools import _tool_actor_context

    org = _FakeOrg()
    org.extra_data = {"founder_user_id": "u1"}
    db = _FakeDB(org=org, depts=["d1", "d2"])
    ctx = await _tool_actor_context(db, _FakeUser())
    assert ctx["actor_user_id"] == "u1"
    assert ctx["actor_departments"] == {"d1", "d2"}
    assert ctx["is_founder"] is True
    assert ctx["granted_record_ids"] == set()


@pytest.mark.asyncio
async def test_tool_actor_context_fail_closed_shape_on_error():
    from aios.api.tools import _tool_actor_context

    class _BadDB:
        async def execute(self, _q):
            raise RuntimeError("db down")

        async def get(self, _m, _id):
            raise RuntimeError("db down")

    ctx = await _tool_actor_context(_BadDB(), _FakeUser())
    assert ctx["actor_user_id"] == "u1"
    assert ctx["actor_departments"] == set()
    assert ctx["is_founder"] is False
    assert ctx["granted_record_ids"] == set()


@pytest.mark.asyncio
async def test_dashboard_tool_actor_context_fail_closed_without_user(monkeypatch):
    from aios.dashboard import app as dashboard_app

    async def _no_user(_request):
        return None

    monkeypatch.setattr("aios.api.deps.get_dashboard_user", _no_user)
    ctx = await dashboard_app._dashboard_tool_actor_context(object())
    assert ctx == {"_unresolved": True}


@pytest.mark.asyncio
async def test_dashboard_tool_actor_context_wires_user(monkeypatch):
    from aios.dashboard import app as dashboard_app

    class _Req:
        pass

    async def _user(_request):
        return _FakeUser()

    org = _FakeOrg()
    org.extra_data = {"founder_user_id": "u1"}
    fake_db = _FakeDB(org=org, depts=["d1"])

    class _DBCtx:
        async def __aenter__(self):
            return fake_db

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("aios.api.deps.get_dashboard_user", _user)
    monkeypatch.setattr(dashboard_app, "db_session", lambda: _DBCtx())
    ctx = await dashboard_app._dashboard_tool_actor_context(_Req())
    assert ctx["actor_user_id"] == "u1"
    assert ctx["actor_departments"] == {"d1"}
    assert ctx["is_founder"] is True
    assert ctx["granted_record_ids"] == set()
    assert "_unresolved" not in ctx


async def _coro(val):
    return val
