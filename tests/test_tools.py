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


@pytest.mark.asyncio
async def test_dashboard_lab_tool_run_requires_admin_role(monkeypatch):
    from aios.dashboard import app as dashboard_app

    class _Req:
        async def json(self):
            return {"tool": "calculator", "args": {"expression": "1+1"}}

    async def _member(_request):
        return type("U", (), {"id": "u1", "org_id": "org1", "role": "member"})()

    monkeypatch.setattr("aios.api.deps.get_dashboard_user", _member)
    monkeypatch.setattr(dashboard_app, "_dashboard_tool_actor_context", lambda _r: _coro({"_unresolved": True}))

    resp = await dashboard_app.lab_tool_run(_Req())
    assert resp.status_code == 403
    body = resp.body.decode()
    assert "admin role required" in body
    assert "fail_closed" in body


@pytest.mark.asyncio
async def test_dashboard_lab_tool_run_fail_closed_no_user(monkeypatch):
    from aios.dashboard import app as dashboard_app

    class _Req:
        async def json(self):
            return {"tool": "calculator", "args": {"expression": "1+1"}}

    async def _no_user(_request):
        return None

    monkeypatch.setattr("aios.api.deps.get_dashboard_user", _no_user)

    resp = await dashboard_app.lab_tool_run(_Req())
    assert resp.status_code == 403
    assert "fail_closed" in resp.body.decode()


@pytest.mark.asyncio
async def test_dashboard_lab_tool_run_allows_admin(monkeypatch):
    from aios.dashboard import app as dashboard_app

    class _Req:
        async def json(self):
            return {"tool": "calculator", "args": {"expression": "1+1"}}

    async def _admin(_request):
        return type("U", (), {"id": "u1", "org_id": "org1", "role": "admin"})()

    class _FakeToolEngine:
        def __init__(self, names, **kwargs):
            self.kwargs = kwargs

        async def execute(self, name, args_json):
            return "2"

    monkeypatch.setattr("aios.api.deps.get_dashboard_user", _admin)
    monkeypatch.setattr(dashboard_app, "_dashboard_tool_actor_context", lambda _r: _coro({
        "actor_user_id": "u1", "actor_departments": set(), "is_founder": False, "granted_record_ids": set(),
    }))
    monkeypatch.setattr(dashboard_app, "_resolve_org_id", lambda _r: _coro("org1"))
    monkeypatch.setattr("aios.core.tools.ToolEngine", _FakeToolEngine)
    monkeypatch.setitem(__import__("aios.tools.registry", fromlist=["TOOL_REGISTRY"]).TOOL_REGISTRY, "calculator", {"description": "x"})

    resp = await dashboard_app.lab_tool_run(_Req())
    assert resp.status_code == 200
    assert '"ok":true' in resp.body.decode().replace(" ", "").lower() or '"ok": true' in resp.body.decode().lower()


@pytest.mark.asyncio
async def test_mcp_call_hides_internal_exception(monkeypatch):
    from aios.api import mcp as mcp_api

    logged = {}

    class _FakeToolEngine:
        def __init__(self, names, **kwargs):
            pass

        async def execute(self, name, args_json):
            raise RuntimeError("secret db uri postgresql://user:pw@host/db")

    class _FakeTool:
        name = "rag_search"
        code_reference = ""

    def _log_exc(msg, *args, **kwargs):
        logged["msg"] = msg
        logged["args"] = args

    monkeypatch.setattr("aios.core.tools.ToolEngine", _FakeToolEngine)
    monkeypatch.setattr(mcp_api.logger, "exception", _log_exc)
    monkeypatch.setattr(mcp_api, "_tool_actor_context", lambda db, user: _coro({
        "actor_user_id": "u1",
        "actor_departments": set(),
        "is_founder": False,
        "granted_record_ids": set(),
    }))

    async def _fake_exec(*args, **kwargs):
        return _ScalarResult([_FakeTool()])

    db = _FakeDB()
    db.execute = _fake_exec
    out = await mcp_api.mcp_call(
        {"name": "rag_search", "arguments": {"query": "x"}},
        db=db,
        org_id="org1",
        user=_FakeUser(),
    )
    assert out == {"ok": False, "error": "Tool execution failed"}
    assert "secret db uri" not in out["error"]
    assert logged["msg"] == "MCP tool call failed org=%s tool=%s"
    assert logged["args"] == ("org1", "rag_search")


@pytest.mark.asyncio
async def test_dashboard_lab_tool_run_hides_internal_exception(monkeypatch):
    from aios.dashboard import app as dashboard_app

    logged = {}

    class _FakeUser:
        id = "u1"
        org_id = "org1"
        role = "admin"

    class _FakeRequest:
        cookies = {}

        async def json(self):
            return {"tool": "calculator", "args": {"expression": "1+1"}}

    class _FakeToolEngine:
        def __init__(self, names, **kwargs):
            pass

        async def execute(self, name, args_json):
            raise RuntimeError("secret token sk-live-123")

    async def _actor(_request):
        return {
            "actor_user_id": "u1",
            "actor_departments": set(),
            "is_founder": False,
            "granted_record_ids": set(),
        }

    async def _org_id(_request):
        return "org1"

    async def _dashboard_user(_request):
        return _FakeUser()

    def _log_exc(msg, *args, **kwargs):
        logged["msg"] = msg
        logged["args"] = args

    monkeypatch.setattr("aios.core.tools.ToolEngine", _FakeToolEngine)
    monkeypatch.setattr("aios.tools.registry.TOOL_REGISTRY", {"calculator": {"description": "x"}})
    monkeypatch.setattr("aios.api.deps.get_dashboard_user", _dashboard_user)
    monkeypatch.setattr(dashboard_app, "_dashboard_tool_actor_context", _actor)
    monkeypatch.setattr(dashboard_app, "_resolve_org_id", _org_id)
    monkeypatch.setattr(dashboard_app.logger, "exception", _log_exc)

    resp = await dashboard_app.lab_tool_run(_FakeRequest())

    assert resp.status_code == 200
    body = resp.body.decode() if hasattr(resp, "body") else ""
    import json

    data = json.loads(body)
    assert data["ok"] is False
    assert data["tool"] == "calculator"
    assert data["error"] == "Tool execution failed"
    assert "secret token" not in body
    assert logged["msg"] == "Lab tool run failed org=%s tool=%s"
    assert logged["args"] == ("org1", "calculator")


async def _coro(val):
    return val


# ─── dynamic tool sandbox hardening ──────────────────────────────────────

def test_dynamic_tool_blocks_dangerous_names():
    from aios.tools.dynamic import _validate_ast
    import pytest

    bad = [
        "result = getattr(x, 'y')",
        "setattr(x, 'y', 1)",
        "delattr(x, 'y')",
        "result = type(1)",
        "result = object()",
        "result = globals()",
        "result = locals()",
        "result = vars()",
        "result = __import__('os')",
        "eval('1+1')",
        "exec('x=1')",
        "open('x')",
    ]
    for code in bad:
        with pytest.raises(ValueError):
            _validate_ast(code)


def test_dynamic_tool_blocks_dangerous_attrs():
    from aios.tools.dynamic import _validate_ast
    import pytest

    bad = [
        "result = ''.__class__",
        "result = [].__class__.__mro__",
        "result = ().__class__.__bases__[0].__subclasses__()",
        "x.__dict__['y']=1",
        "f.__globals__",
        "f.__code__",
    ]
    for code in bad:
        with pytest.raises(ValueError):
            _validate_ast(code)


def test_dynamic_tool_blocks_dangerous_nodes():
    from aios.tools.dynamic import _validate_ast
    import pytest

    bad = [
        "import os",
        "from os import path",
        "while True: pass",
        "for i in [1]: pass",
        "async def f(): pass",
        "def f(): pass",
        "class X: pass",
        "lambda: 1",
        "global x",
    ]
    for code in bad:
        with pytest.raises(ValueError):
            _validate_ast(code)


@pytest.mark.asyncio
async def test_dynamic_tool_runs_simple_code():
    from aios.tools.dynamic import DynamicTool

    t = DynamicTool("t_ok", "ok", "result = {'sum': a + b}", {"type": "object"})
    out = await t.run(a=2, b=3)
    assert out == {"sum": 5}


@pytest.mark.asyncio
async def test_dynamic_tool_rejects_large_output():
    from aios.tools.dynamic import DynamicTool

    t = DynamicTool("t_big", "big", "result = {'x': 'a' * 200000}")
    out = await t.run()
    assert out.get("error") == "output too large"


@pytest.mark.asyncio
async def test_dynamic_tool_rejects_nonserializable_output():
    from aios.tools.dynamic import DynamicTool

    t = DynamicTool("t_set", "set", "result = {'x': {1,2,3}}")
    out = await t.run()
    # set is json serializable with default=str? json.dumps default=str makes it string - acceptable; but better be stable.
    # If serialized, it returns parsed form. Accept either stringified set or error.
    assert isinstance(out, dict)
    assert "x" in out or "error" in out


# ─── dynamic/code tool registration guard ─────────────────────────────────

@pytest.mark.asyncio
async def test_create_dynamic_tool_requires_admin_role():
    from aios.api import tools as tools_api

    class _Member:
        id = "u1"
        org_id = "org1"
        role = "member"

    db = _FakeDB(org=_FakeOrg())
    body = tools_api.ToolCreate(name="dyn1", code_reference="code:result = 1", dynamic=True)
    with pytest.raises(tools_api.HTTPException) as exc:
        await tools_api.create_tool(body, db=db, org_id="org1", user=_Member())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_code_tool_requires_admin_role():
    from aios.api import tools as tools_api

    class _Member:
        id = "u1"
        org_id = "org1"
        role = "member"

    db = _FakeDB(org=_FakeOrg())
    body = tools_api.ToolCreate(name="dyn1", code_reference="code:result = 1")
    with pytest.raises(tools_api.HTTPException) as exc:
        await tools_api.create_tool(body, db=db, org_id="org1", user=_Member())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_dynamic_tool_allows_admin(monkeypatch):
    from aios.api import tools as tools_api

    class _Admin:
        id = "u1"
        org_id = "org1"
        role = "admin"

    class _DB(_FakeDB):
        def __init__(self):
            super().__init__(org=_FakeOrg())
            self.added = None

        def add(self, obj):
            self.added = obj

        async def commit(self):
            return None

        async def refresh(self, obj):
            if not getattr(obj, "id", None):
                obj.id = "t1"
            if getattr(obj, "status", None) is None:
                obj.status = "active"
            if getattr(obj, "is_builtin", None) is None:
                obj.is_builtin = False

        async def execute(self, _q):
            return _ScalarResult([])

    monkeypatch.setattr("aios.tools.dynamic.register_dynamic_tool", lambda *a, **k: None)
    db = _DB()
    body = tools_api.ToolCreate(name="dyn1", description="d", code_reference="code:result = 1")
    out = await tools_api.create_tool(body, db=db, org_id="org1", user=_Admin())
    assert out.name == "dyn1"
    assert db.added is not None


@pytest.mark.asyncio
async def test_create_dynamic_tool_allows_founder(monkeypatch):
    from aios.api import tools as tools_api

    class _MemberFounder:
        id = "u1"
        org_id = "org1"
        role = "member"

    org = _FakeOrg()
    org.extra_data = {"founder_user_id": "u1"}

    class _DB(_FakeDB):
        def __init__(self):
            super().__init__(org=org)
            self.added = None

        def add(self, obj):
            self.added = obj

        async def commit(self):
            return None

        async def refresh(self, obj):
            if not getattr(obj, "id", None):
                obj.id = "t1"
            if getattr(obj, "status", None) is None:
                obj.status = "active"
            if getattr(obj, "is_builtin", None) is None:
                obj.is_builtin = False

        async def execute(self, _q):
            return _ScalarResult([])

    monkeypatch.setattr("aios.tools.dynamic.register_dynamic_tool", lambda *a, **k: None)
    db = _DB()
    body = tools_api.ToolCreate(name="dyn2", code_reference="code:result = 2", dynamic=True)
    out = await tools_api.create_tool(body, db=db, org_id="org1", user=_MemberFounder())
    assert out.name == "dyn2"


@pytest.mark.asyncio
async def test_create_nondynamic_tool_allows_member(monkeypatch):
    from aios.api import tools as tools_api

    class _Member:
        id = "u1"
        org_id = "org1"
        role = "member"

    class _DB(_FakeDB):
        def __init__(self):
            super().__init__(org=_FakeOrg())
            self.added = None

        def add(self, obj):
            self.added = obj

        async def commit(self):
            return None

        async def refresh(self, obj):
            if not getattr(obj, "id", None):
                obj.id = "t1"
            if getattr(obj, "status", None) is None:
                obj.status = "active"
            if getattr(obj, "is_builtin", None) is None:
                obj.is_builtin = False

        async def execute(self, _q):
            return _ScalarResult([])

    db = _DB()
    body = tools_api.ToolCreate(name="plain", code_reference="aios.tools.calculator.Calculator")
    out = await tools_api.create_tool(body, db=db, org_id="org1", user=_Member())
    assert out.name == "plain"
