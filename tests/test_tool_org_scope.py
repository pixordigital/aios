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


def test_registry_consistent_after_importing_every_tool_module():
    """Order-dependent gap: whatsapp_template registered on import but was not
    allow-listed, so it only failed when another test imported it first."""
    import importlib
    import pkgutil

    import aios.tools as tools_pkg
    from aios.core.tools import ToolEngine
    from aios.tools.registry import TOOL_REGISTRY

    for m in pkgutil.iter_modules(tools_pkg.__path__):
        if not m.name.startswith("_"):
            try:
                importlib.import_module(f"aios.tools.{m.name}")
            except Exception:
                pass  # optional deps (calendar) — unrelated to the allow-list

    eng = ToolEngine([])
    broken = []
    for name in TOOL_REGISTRY:
        try:
            eng._load(name)
        except Exception as e:
            broken.append(f"{name}: {e}")
    assert not broken, broken


class TestSqlOrgScopeBypass:
    """CRITICAL regression: the org guard used to be satisfied by an
    org_id='<mine>' literal appearing ANYWHERE in the query. Every case below
    passed that check while returning every org's rows -- verified against a
    seeded two-org database, where org-mine read org-vitima's row.

    A predicate only constrains a result if nothing can widen it again, so the
    guard now rejects OR, UNION, subqueries, always-true predicates, comments,
    and any org_id test that is not plain equality with the caller's org.
    """

    def _tool(self, org="org-mine"):
        from aios.tools.sql_query import SQLQueryTool
        t = SQLQueryTool()
        t._org_id = org
        return t

    @pytest.mark.asyncio
    @pytest.mark.parametrize("q", [
        "SELECT * FROM agents WHERE org_id = 'org-mine' OR 1=1",
        "SELECT * FROM agents WHERE org_id='org-mine' OR true",
        "SELECT * FROM agents WHERE org_id='org-mine' OR 'x'='x'",
        "SELECT * FROM agents WHERE org_id='org-mine' "
        "UNION ALL SELECT * FROM agents",
        "SELECT * FROM agents WHERE org_id='org-mine' "
        "AND id IN (SELECT id FROM agents)",
        "SELECT * FROM agents WHERE 1=1 /* org_id='org-mine' */",
        "SELECT * FROM agents WHERE org_id LIKE 'org-%'",
        "SELECT * FROM agents WHERE org_id <> 'org-vitima'",
        "SELECT * FROM agents WHERE org_id IN ('org-mine','org-vitima')",
        "SELECT * FROM agents",
    ])
    async def test_bypass_attempt_is_blocked(self, q):
        assert "error" in await self._tool().run(query=q), q

    @pytest.mark.asyncio
    @pytest.mark.parametrize("q", [
        "SELECT * FROM agents WHERE org_id = 'org-mine'",
        "SELECT * FROM agents WHERE org_id='org-mine' AND status='active'",
        "SELECT a.name FROM agents a JOIN crm_deals c ON c.org_id=a.org_id "
        "WHERE a.org_id='org-mine' AND c.org_id='org-mine'",
        "SELECT * FROM agents WHERE status='active' AND org_id='org-mine'",
    ])
    async def test_legitimate_scoped_query_still_works(self, q):
        res = await self._tool().run(query=q)
        assert "error" not in res, res.get("error")

    @pytest.mark.asyncio
    async def test_commented_duplicate_org_id_is_not_a_bypass(self):
        """A commented-out second org_id is ignored by SQL, so the query really
        is scoped to the caller's org and must be allowed to run. Pinning the
        opposite would push operators toward deleting real WHERE clauses."""
        t = self._tool()
        res = await t.run(query="SELECT * FROM agents WHERE org_id='org-mine' -- org_id='x'")
        assert "error" not in res

    @pytest.mark.asyncio
    async def test_unknown_caller_org_blocks_everything(self):
        """No caller org -> no safe scoping is possible, so fail closed."""
        from aios.tools.sql_query import SQLQueryTool
        t = SQLQueryTool()
        assert "_org_id" not in t.__dict__
        res = await t.run(query="SELECT * FROM agents WHERE org_id='org-mine'")
        assert "error" in res

    @pytest.mark.asyncio
    async def test_mask_preserves_structure_and_length(self):
        from aios.tools.sql_query import SQLQueryTool
        q = "SELECT * FROM agents WHERE note='1=1' /* OR */ AND org_id='o'"
        masked = SQLQueryTool._mask(q)
        assert len(masked) == len(q)
        assert "FROM" in masked          # structure survives
        assert "1=1" not in masked       # string body hidden
        assert "OR" not in masked        # comment hidden
