"""Tools that could not succeed at all, and guards that could be walked past.

Every defect here made an autonomous agent fail outright or reach data it must
not reach. Each test fails if the defect returns.
"""

import asyncio
import json

import pytest

from aios.core.tools import ToolEngine
from aios.tools.base import BaseTool


# ─── tools that raised on 100% of calls ───────────────────────────────────

@pytest.mark.asyncio
async def test_current_datetime_returns_the_time():
    """`timezone` was both this tool's run() parameter and the module it tried
    to use as `timezone.utc`, so the parameter shadowed the import and every
    call raised AttributeError."""
    eng = ToolEngine(["current_datetime"], org_id="o", agent_id="a")
    out = json.loads(await eng.execute("current_datetime", "{}"))
    assert out["utc"], out
    tz = json.loads(await eng.execute("current_datetime", json.dumps({"timezone": "America/New_York"})))
    assert tz["local"] != tz["utc"], "timezone argument was ignored"


@pytest.mark.asyncio
async def test_http_get_rejects_plain_http_instead_of_raising_nameerror():
    """`urlparse` was used but never imported, on a line outside the try, so the
    NameError became a ToolExecutionError instead of the guard's own answer."""
    eng = ToolEngine(["http_get"], org_id="o", agent_id="a")
    out = json.loads(await eng.execute("http_get", json.dumps({"url": "http://example.com"})))
    assert out.get("error") == "Only HTTPS URLs allowed", out


@pytest.mark.asyncio
async def test_code_tool_executes():
    """Its own wrapper did `import json, sys` (sys is deny-listed) and called
    `dir()` (a denied builtin), so the sandbox rejected it every time."""
    eng = ToolEngine(["code"], org_id="o", agent_id="a")
    out = json.loads(
        await eng.execute("code", json.dumps({"code": "x = 6*7\noutput = x"}))
    )
    assert out.get("ok") and out.get("output") == 42, out


@pytest.mark.asyncio
async def test_customer_authored_dynamic_tool_runs():
    """ToolEngine routed dynamic tools to a sandbox runner that imported
    asyncio (deny-listed) and referenced an undefined `tool_instance`, so
    100% of "write your own tool" tools failed."""
    from aios.tools.dynamic import register_dynamic_tool, TOOL_REGISTRY

    register_dynamic_tool(
        "t_dyn_probe", "doubles",
        "result = {'doubled': _input['n'] * 2}",
        {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
    )
    try:
        eng = ToolEngine(["t_dyn_probe"], org_id="o", agent_id="a")
        out = json.loads(await eng.execute("t_dyn_probe", json.dumps({"n": 21})))
        assert out == {"doubled": 42}, out
    finally:
        # Clean up dynamic tool to not pollute global registry for other tests
        from aios.tools.dynamic import TOOL_REGISTRY
        TOOL_REGISTRY.pop("t_dyn_probe", None)


# ─── the schema the model is shown ────────────────────────────────────────

@pytest.mark.parametrize(
    "name,expected",
    [
        ("sql_query", "query"),
        ("python_sandbox", "code"),
        ("lead_score", "email"),
        ("crm_create_deal", "lead_email"),
        ("crm_merge_deals", "lead_email"),
    ],
)
def test_tool_advertises_its_arguments(name, expected):
    """`openai_schema` read only `input_model`, which these tools defined but
    never assigned, so the model was shown `"parameters": {}`, sent `{}`, and
    every call died on a missing argument."""
    eng = ToolEngine([name], org_id="o", agent_id="a")
    params = eng.schemas()[0]["function"]["parameters"]
    assert expected in (params.get("properties") or {}), (
        f"{name} advertises no arguments: {params}"
    )


def test_dynamic_tool_schema_is_preserved():
    eng = ToolEngine(["whatsapp_template_list"], org_id="o", agent_id="a")
    props = eng.schemas()[0]["function"]["parameters"].get("properties") or {}
    assert props, "whatsapp_template_list advertises no arguments"


# ─── guards the model could walk past ─────────────────────────────────────

def _sql():
    from aios.tools.sql_query import SQLQueryTool

    return SQLQueryTool()


@pytest.mark.parametrize(
    "query,table",
    [
        ('SELECT * FROM "agents"', "agents"),
        ("SELECT * FROM public.agents", "agents"),
        ('SELECT * FROM "messages"', "messages"),
        ("SELECT * FROM public.messages", "messages"),
    ],
)
def test_quoted_and_schema_qualified_org_tables_still_require_scoping(query, table):
    """The FROM/JOIN patterns ran on the raw text, so `"agents"` and
    `public.agents` matched nothing and the org-scope check never fired."""
    tool = _sql()
    tool._org_id = "org-me"
    assert table in tool._ORG_SCOPED_TABLES
    assert table in tool._referenced_tables(tool._mask(query))


@pytest.mark.parametrize("query", ['SELECT * FROM "users"', "SELECT * FROM public.users"])
def test_quoted_and_schema_qualified_secret_tables_are_denied(query):
    """Same bypass on the secret/PII deny-list: `public.users` read the very
    table the deny-list exists to protect."""
    tool = _sql()
    refs = tool._referenced_tables(tool._mask(query))
    assert "users" in refs
    assert refs & set(tool._DENY_APP_TABLES)


@pytest.mark.asyncio
async def test_scoped_query_is_still_allowed():
    tool = _sql()
    tool._org_id = "org-me"
    assert tool._check_org_scope("SELECT * FROM messages WHERE org_id = 'org-me'") is None


@pytest.mark.asyncio
async def test_unscoped_org_table_is_refused():
    tool = _sql()
    tool._org_id = "org-me"
    err = tool._check_org_scope('SELECT * FROM "agents"')
    assert err, "quoted identifier bypassed the org-scope check"


# ─── cross-tenant reads through the wrong org ──────────────────────────────

@pytest.mark.asyncio
async def test_rag_search_never_falls_back_to_an_arbitrary_org():
    """`select(Organization).limit(1)` returned whichever tenant was first, so
    one tenant's agent retrieved another tenant's knowledge chunks."""
    from aios.tools.rag_search import RagSearchTool

    tool = RagSearchTool()
    tool._org_id = ""
    out = await tool.run(query="qual o preco?")
    assert out["ok"] is False and out["results"] == [], out


# ─── RAG pointed at a column that never existed ───────────────────────────

@pytest.mark.asyncio
async def test_hybrid_search_finds_stored_vectors(tmp_path, monkeypatch):
    """It selected `memories.embedding` from Postgres; that column does not
    exist, so every search raised, was swallowed, and returned []. An agent
    with a knowledge base reported "not found" for everything."""
    from aios.config import settings

    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    from aios.core.memory import MemoryManager
    from aios.core.rag import hybrid_search

    m = MemoryManager("agent-rag-probe")
    await m._store_vector("O cliente prefere ser contatado por email, nunca por telefone")
    await m._store_vector("O prazo de entrega padrao e de cinco dias uteis")

    hits = await hybrid_search("org-x", "como o cliente quer ser contatado",
                               top_k=2, agent_id="agent-rag-probe")
    assert hits, "hybrid_search found nothing in a store it wrote to"
    assert "email" in hits[0]["content"], hits[0]


# ─── org must come from the running agent, never the model ────────────────

@pytest.mark.asyncio
async def test_proactive_alerts_takes_no_org_argument():
    """`org_id` was a required LLM-supplied argument on a tool with no
    input_model, so the model sent `{}` and every call raised TypeError — and a
    model that guessed a UUID would read another tenant's deals."""
    from aios.tools.proactive_alerts import ProactiveAlertsTool

    tool = ProactiveAlertsTool()
    tool._org_id = ""
    out = await tool.run()
    assert out["ok"] is False and "org" in out["error"], out


# ─── retrying something that cannot succeed ───────────────────────────────

def test_argument_shape_errors_are_not_retried():
    """TypeError/ValueError from a bad call shape cannot fix themselves, and
    each retry burned up to another 30s of the agent's wall clock."""
    import inspect

    src = inspect.getsource(ToolEngine.execute)
    for exc in ("TypeError", "ValueError", "KeyError"):
        assert exc in src, f"{exc} is still treated as retryable"


# ─── per-org settings the tools never read ────────────────────────────────

def test_send_email_reads_per_org_smtp():
    """SMTP was hardcoded to smtp.gmail.com with password="", and From was
    set to the recipient, so no tenant could send mail at all."""
    import inspect

    from aios.tools.send_email import SendEmailTool

    src = inspect.getsource(SendEmailTool)
    assert "smtp.gmail.com" not in src
    assert "get_org_secret_async" in src
    assert 'msg["From"] = to' not in src


def test_calendar_reads_per_org_credential():
    """The dashboard writes the tenant's Google credential per-org, but the
    resolver only read env/instance settings."""
    import inspect

    from aios.tools import calendar

    src = inspect.getsource(calendar)
    assert "get_org_secret_async" in src
    assert "_resolve_google(org_id" in src


@pytest.mark.asyncio
async def test_read_file_does_not_wait_for_a_session_nobody_injects():
    """`self._db` was read but never set by ToolEngine, so every call returned
    'File reading requires a database session'."""
    import inspect

    from aios.tools.read_file import ReadFileTool

    src = inspect.getsource(ReadFileTool)
    assert 'getattr(self, "_db"' not in src
    assert "db_session" in src