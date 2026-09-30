"""Org scoping in the agent tool runtime.

Tools ran with a god-view DB session: sql_query could SELECT any org's rows
and read_file resolved any artifact UUID. ToolEngine now carries the caller's
org_id onto each tool before run, and the tools enforce it.
"""

import pytest
from httpx import AsyncClient


class TestSqlOrgScoping:
    def _tool(self, org="org-AAA"):
        from aios.tools.sql_query import SQLQueryTool

        t = SQLQueryTool()
        t._org_id = org
        return t

    @pytest.mark.asyncio
    async def test_sensitive_tables_denied_even_with_org(self):
        t = self._tool()
        for q in [
            "SELECT * FROM users",
            "SELECT * FROM credentials WHERE org_id='org-AAA'",
            "SELECT config FROM channel_connections WHERE org_id='org-AAA'",
        ]:
            res = await t.run(query=q)
            assert "error" in res, q

    @pytest.mark.asyncio
    async def test_scoped_table_requires_own_org(self):
        t = self._tool()
        res = await t.run(query="SELECT count(*) FROM agents")
        assert res.get("error", "").startswith("adicione WHERE org_id")

    @pytest.mark.asyncio
    async def test_other_org_refused(self):
        t = self._tool()
        res = await t.run(query="SELECT * FROM messages WHERE org_id='org-BBB'")
        assert "error" in res

    @pytest.mark.asyncio
    async def test_mixed_org_refused(self):
        t = self._tool()
        res = await t.run(
            query="SELECT * FROM messages WHERE org_id='org-AAA' OR org_id='org-BBB'"
        )
        assert "error" in res

    @pytest.mark.asyncio
    async def test_engine_passes_org_end_to_end(self):
        """Through ToolEngine.execute, not by setting _org_id by hand."""
        from aios.core.tools import ToolEngine

        eng = ToolEngine(["sql_query"], org_id="org-E2E")
        import json

        out = await eng.execute(
            "sql_query", json.dumps({"query": "SELECT * FROM teams WHERE org_id='org-E2E'"})
        )
        assert '"ok": true' in out.lower() or '"ok":true' in out.replace(" ", "")
        out2 = await eng.execute(
            "sql_query", json.dumps({"query": "SELECT * FROM teams"})
        )
        assert "adicione WHERE org_id" in out2


class TestSuperadminGate:
    @pytest.mark.asyncio
    async def test_owner_and_superadmin_pass(self):
        from fastapi import HTTPException

        from aios.api.deps import get_superadmin
        from aios.db.models import User

        for role in ("owner", "superadmin"):
            u = User(email=f"{role}@x.com", hashed_password="x", org_id="o", role=role)
            assert await get_superadmin(u) is u

    @pytest.mark.asyncio
    async def test_member_blocked(self):
        from fastapi import HTTPException

        from aios.api.deps import get_superadmin
        from aios.db.models import User

        u = User(email="m@x.com", hashed_password="x", org_id="o", role="admin")
        with pytest.raises(HTTPException) as e:
            await get_superadmin(u)
        assert e.value.status_code == 403

    async def test_dev_console_forbidden_for_member(self, auth_client: AsyncClient):
        """Test user is role=admin: code-exec console must 403."""
        r = await auth_client.post("/api/dev/claude", json={"prompt": "hi"})
        assert r.status_code == 403


class TestOAuthRefusal:
    async def test_callback_requires_auth(self, async_client: AsyncClient):
        r = await async_client.get("/api/integrations/hubspot/callback?code=x&state=o:n")
        assert r.status_code in (401, 403)

    async def test_callback_rejects_foreign_state(self, auth_client: AsyncClient):
        r = await auth_client.get(
            "/api/integrations/hubspot/callback?code=x&state=org-OTHER:abcd1234"
        )
        assert r.json().get("error") == "state inválido"


def test_no_x_api_key_param():
    import inspect

    from aios.api.deps import get_current_user

    assert "x_api_key" not in inspect.signature(get_current_user).parameters


class TestRegistryConsistency:
    """Every registered tool must load. Four modules sat in the registry for
    months while the allow-list rejected them — no agent could call them and
    nothing said so."""

    def test_all_registered_tools_load(self):
        from aios.core.tools import ToolEngine
        from aios.tools.registry import TOOL_REGISTRY

        eng = ToolEngine([])
        broken = []
        for name in TOOL_REGISTRY:
            try:
                eng._load(name)
            except Exception as e:
                broken.append(f"{name}: {e}")
        assert not broken, f"tools that cannot load: {broken}"

    def test_allow_list_covers_registry(self):
        from aios.core.tools import _ALLOWED_MODULES
        from aios.tools.registry import TOOL_REGISTRY

        missing = set()
        for name, entry in TOOL_REGISTRY.items():
            mod = entry["code_reference"].rsplit(".", 1)[0]
            if mod not in _ALLOWED_MODULES:
                missing.add(f"{name} ({mod})")
        assert not missing, f"registered but not allow-listed: {missing}"
