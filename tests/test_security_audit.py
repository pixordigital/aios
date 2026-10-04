"""Regression guards for the holes the security audit closed.

Each test here corresponds to a defect that was live in main, not a
theoretical one. They are deliberately cheap and dependency-free so they run in
CI without a database or network.
"""

import hashlib
import hmac

import pytest

SECRET = "webhook-secret-under-test"


class _FakeRequest:
    """Minimal Request stand-in: the validator only needs body() + headers."""

    def __init__(self, body: bytes, headers: dict | None = None):
        self._body = body
        self.headers = headers or {}

    async def body(self) -> bytes:
        return self._body


def _sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# --- webhook signature verification -----------------------------------------

async def test_missing_signature_header_is_rejected():
    """The validator used to read `if secret and sig:`, so a request with NO
    signature header skipped the HMAC entirely and returned ok=True. Any
    unauthenticated caller could then drive the LGPD-consent write and pick the
    target org from the instance name in the URL."""
    from aios.core.whatsapp.webhook_validator import validate

    res = await validate(_FakeRequest(b'{"message":"stop"}', {}), SECRET, None)
    assert res["ok"] is False
    assert res["reason"] == "missing signature"


async def test_empty_signature_header_is_rejected():
    from aios.core.whatsapp.webhook_validator import validate

    res = await validate(
        _FakeRequest(b'{"message":"stop"}', {"x-hub-signature-256": ""}), SECRET, None
    )
    assert res["ok"] is False
    assert res["reason"] == "missing signature"


async def test_unset_secret_rejects_everything():
    """Fail closed: with no secret configured the old code accepted anything,
    because the `secret and sig` guard skipped verification entirely."""
    from aios.core.whatsapp.webhook_validator import validate

    body = b'{"message":"stop"}'
    res = await validate(_FakeRequest(body, {"x-hub-signature-256": _sig(SECRET, body)}), "", None)
    assert res["ok"] is False


async def test_valid_signature_still_passes():
    from aios.core.whatsapp.webhook_validator import validate

    body = b'{"message":"stop"}'
    res = await validate(_FakeRequest(body, {"x-hub-signature-256": _sig(SECRET, body)}), SECRET, None)
    assert res["ok"] is True


async def test_forged_signature_is_rejected():
    from aios.core.whatsapp.webhook_validator import validate

    res = await validate(
        _FakeRequest(b"{}", {"x-hub-signature-256": "sha256=" + "0" * 64}), SECRET, None
    )
    assert res["ok"] is False
    assert res["reason"] == "invalid signature"


# --- credential storage ------------------------------------------------------

def test_ciphertext_wins_over_stale_cleartext():
    """get_org_secret used to check extra_data["secrets"] FIRST, so a legacy
    cleartext value shadowed the encrypted one and the encryption was
    decorative. Reading order now lives in all_org_secrets."""
    from aios.config import settings
    from aios.core.org_settings import get_org_secret
    from aios.core.secrets import encrypt_secret

    previous = settings.encryption_key
    settings.encryption_key = "unit-test-encryption-key-0123456789"
    try:
        row = {
            "secrets": {"openai_api_key": "sk-STALE-CLEARTEXT"},
            "_secrets_enc": {"openai_api_key": encrypt_secret("sk-ENCRYPTED")},
        }
        assert get_org_secret(row, "openai_api_key") == "sk-ENCRYPTED"
    finally:
        settings.encryption_key = previous


def test_legacy_cleartext_row_is_still_readable():
    """Encrypting on write must not orphan credentials already stored in the
    clear before this change."""
    from aios.core.org_settings import get_org_secret

    row = {"secrets": {"smtp_password": "legacy-plain"}}
    assert get_org_secret(row, "smtp_password") == "legacy-plain"


def test_channel_config_is_encrypted_on_write():
    """create_channel persisted body.config verbatim, so a Slack bot token
    sat in cleartext while every other path encrypted it."""
    from aios.core.secrets import decrypt_channel_config, encrypt_channel_config

    original = {"bot_token": "xoxb-secret", "channel": "C123"}
    stored = encrypt_channel_config(original)
    assert stored["bot_token"] != "xoxb-secret"
    assert decrypt_channel_config(stored)["bot_token"] == "xoxb-secret"


# --- tenant isolation in the SQL tool ----------------------------------------

@pytest.mark.parametrize(
    "table",
    ["pending_actions", "audit_logs", "crm_deal_versions", "swarm_messages"],
)
def test_every_org_table_requires_an_org_filter(table):
    """30 org_id tables sat in neither the scoped nor the denied list, so
    _check_org_scope never ran and any tenant could SELECT every org's rows.
    The scoped set is now derived from the models."""
    import asyncio

    from aios.tools.sql_query import SQLQueryTool

    tool = SQLQueryTool()
    tool._org_id = "mine"
    res = asyncio.run(tool.run(f"SELECT * FROM {table}"))
    assert "error" in res, f"{table} is readable without an org filter"


def test_scoped_query_is_still_allowed():
    import asyncio

    from aios.tools.sql_query import SQLQueryTool

    tool = SQLQueryTool()
    tool._org_id = "mine"
    res = asyncio.run(tool.run("SELECT * FROM agents WHERE org_id='mine'"))
    assert "error" not in res


@pytest.mark.parametrize(
    "query",
    [
        "SELECT pg_read_file('/app/.env')",
        "SELECT lo_export(lo_import('/etc/passwd'))",
        "SELECT pg_copy_file('/app/.env', '/tmp/x')",
        "SELECT pg_sleep(600)",
    ],
)
def test_server_side_file_and_dos_functions_are_blocked(query):
    """The pg_ check only looked at FROM/JOIN table position, never at call
    position, so these all passed validation."""
    import asyncio

    from aios.tools.sql_query import SQLQueryTool

    tool = SQLQueryTool()
    tool._org_id = "mine"
    res = asyncio.run(tool.run(query))
    assert "error" in res


# --- dashboard rendering -----------------------------------------------------

def test_escape_helper_exists_once_in_base():
    """Five templates carried a private copy of esc(); the XSS fixes depend on
    a single shared definition, so it must live in base.html."""
    from pathlib import Path

    base = Path(__file__).resolve().parents[1] / "aios/dashboard/templates/base.html"
    assert "window.esc" in base.read_text()


def test_untrusted_dom_sinks_are_escaped():
    """conversation_detail renders LLM output (which echoes inbound WhatsApp
    text) into innerHTML. Every such interpolation must go through esc()."""
    from pathlib import Path

    tpl = (
        Path(__file__).resolve().parents[1]
        / "aios/dashboard/templates/conversation_detail.html"
    ).read_text()
    for field in ("t.response", "t.reflection", "p.context_summary", "JSON.stringify(p.tool_args)"):
        # The field must be wrapped in esc(...), whatever expression it sits in.
        idx = tpl.find(field)
        assert idx != -1, f"{field} not found in template"
        window = tpl[max(0, idx - 60): idx]
        assert "esc(" in window, f"{field} is interpolated unescaped"


# --- privilege escalation ----------------------------------------------------

def test_invitable_roles_are_allowlisted():
    """member_invite took `role` straight off the form with no allowlist, so
    any member could mint an admin invitation for a second mailbox."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "aios/dashboard/app.py").read_text()
    assert "_INVITABLE_ROLES" in src
    assert '"superadmin"' not in src.split("_INVITABLE_ROLES = {")[1].split("}")[0]


def test_fleet_admin_routes_require_superadmin():
    """These two routes took no request param and never called
    _require_superadmin, so any authenticated member could delete another
    tenant's fleet entry or read its internal base_url."""
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "aios/dashboard/app.py").read_text()
    for route in ("/admin/fleet/{fid}/open", "/admin/fleet/{fid}/remove"):
        m = re.search(rf'@router\.get\("{re.escape(route)}"\)\nasync def \w+\(([^)]*)\)', src)
        assert m, f"{route} signature not found"
        assert "request: Request" in m.group(1), f"{route} takes no request"
        tail = src[m.end(): m.end() + 400]
        assert "_require_superadmin" in tail, f"{route} has no superadmin gate"


# --- sandbox: the AST allowlist and the alias bypass ------------------------

@pytest.mark.parametrize(
    "code",
    [
        'e = exec\ne("import os")',
        'o = open\no("/etc/passwd")',
        'i = __import__\ni("os")',
        'f = lambda: open',
        'for open in [1]: pass',
        'import os',
        'import subprocess',
        '__import__("os").system("id")',
        'eval("1+1")',
        'from os import path',
    ],
)
def test_sandbox_blocks_escape_attempts(code):
    """The denylist only matched syntactic call names, so aliasing a banned name
    to a variable bypassed it completely. It is now an import allowlist plus a
    rule that denied names cannot be bound or referenced at all."""
    from aios.core.sandbox import validate_code

    assert validate_code(code) is not None


@pytest.mark.parametrize(
    "code",
    [
        "import pandas as pd\nprint(pd.DataFrame({'a': [1]}).a.sum())",
        "from collections import Counter\nprint(Counter('aab').most_common(1))",
        "import math, json\nprint(math.sqrt(9), json.dumps({'a': 1}))",
    ],
)
def test_sandbox_still_allows_data_analysis(code):
    from aios.core.sandbox import validate_code

    assert validate_code(code) is None


def test_sandbox_default_memory_fits_pandas():
    """RLIMIT_AS of 128MB killed the interpreter at `import pandas`, so the
    documented data-analysis support could not run at the old default."""
    import inspect

    from aios.core.sandbox import run_isolated

    default = inspect.signature(run_isolated).parameters["max_memory_mb"].default
    assert default >= 512


def test_sandbox_timeout_kills_the_process_group():
    """A forked grandchild inherited nothing useful from RLIMIT_CPU and used to
    keep running after the caller was already told `timeout`."""
    import time

    import pytest as _pytest

    from aios.core.sandbox import run_isolated

    @_pytest.mark.asyncio
    async def _run():
        started = time.time()
        res = await run_isolated("while True: pass", timeout=2.0)
        return res, time.time() - started

    import asyncio

    res, elapsed = asyncio.run(_run())
    assert elapsed < 20
    assert res["ok"] is False


# --- build-request guard ----------------------------------------------------

@pytest.mark.parametrize(
    ("text", "blocked"),
    [
        ("voces conseguem me ajudar a montar uma tela de checkout?", True),
        ("montem um formulario de lead", True),
        ("construam um checkout", True),
        ("precisamos de uma nova tela de checkout para o funil", True),
        # information and inspection asks must still get through
        ("revisa a migration?", False),
        ("como esta a integracao que voces construiram?", False),
        ("qual o status do deploy?", False),
        ("podem me passar o schema do banco?", False),
        ("o deploy quebrou?", False),
        ("confere o erro de prod?", False),
    ],
)
def test_build_guard_classification(text, blocked):
    """ask_team_manager is default-deny for build-capable teams: only a
    recognisably informational ask passes. A bare keyword denylist let
    "montar uma tela" through, and "montar" was not even a recognised stem."""
    from aios.tools.team_collaboration import (
        _is_build_capable,
        _looks_like_build_request,
        _looks_like_information_request,
    )

    refused = _looks_like_build_request(text) or (
        _is_build_capable("Dev") and not _looks_like_information_request(text)
    )
    assert refused is blocked


# --- refresh token revocation ------------------------------------------------

async def test_refresh_token_carries_a_persisted_jti():
    """Refresh tokens were stateless: 30 days, unrotated, and valid after both
    logout and a password reset."""
    from sqlalchemy import select

    from aios.api import auth as A
    from aios.db.models import RefreshToken

    class _Row:
        id = "u1"
        email = "a@b.c"

    class _DB:
        def __init__(self):
            self.added = []

        def add(self, obj):
            self.added.append(obj)

        async def commit(self):
            pass

        async def get(self, model, ident):
            return None

    db = _DB()
    token = await A._issue_refresh(db, "u1")
    payload = A._verify_jwt_token(token)
    assert payload.get("jti")
    assert len(db.added) == 1
    assert isinstance(db.added[0], RefreshToken)


def test_expired_at_normalises_naive_datetimes():
    """DateTime columns come back naive from both SQLite and Postgres, and
    comparing that to an aware now() raised TypeError on every /refresh."""
    from datetime import datetime, timezone

    from aios.api.auth import _as_utc

    naive = datetime(2030, 1, 1, 12, 0, 0)
    assert _as_utc(naive).tzinfo is timezone.utc
    aware = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert _as_utc(aware) == aware
    assert _as_utc(None) is None


# --- CRM kanban must not be hidden behind the paid flag --------------------

def _template_ast():
    from jinja2 import Environment, nodes

    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1] / "aios/dashboard/templates/crm.html"
    ).read_text()
    return Environment().parse(src)


def _gated_markers(ast):
    """Map each literal marker in crm.html to whether it sits in a crm_enabled branch."""
    from jinja2 import nodes

    def has_name(n, name):
        for x in n.iter_child_nodes():
            if isinstance(x, nodes.Name) and x.name == name:
                return True
            if has_name(x, name):
                return True
        return False

    def walk(n, gated=False):
        if isinstance(n, nodes.If) and has_name(n.test, "crm_enabled"):
            gated = True
        yield n, gated
        for c in n.iter_child_nodes():
            yield from walk(c, gated)

    out: dict[str, bool] = {}
    for n, g in walk(ast):
        d = getattr(n, "data", None)
        if isinstance(d, str):
            for key in ("crm-board", "Total de negócios", "HITL"):
                if key in d:
                    out[key] = out.get(key, False) or g
    return out


def test_crm_kanban_board_is_not_behind_the_paid_flag():
    """The board and the pipeline totals used to render only when crm_enabled,
    so an org without the paid flag got the upsell banner and no view of its own
    pipeline at all. Reading your own CRM is not the upsell; only the agents
    operating it are."""
    marks = _gated_markers(_template_ast())
    assert marks.get("crm-board") is False
    assert marks.get("Total de negócios") is False
    # The HITL approval queue IS the paid agent-operating feature: it stays gated.
    assert marks.get("HITL") is True


def test_crm_page_loads_deals_regardless_of_the_flag():
    """The query itself was behind the flag, so ungating the template alone
    would render an empty board. This is the guard on that."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1] / "aios/dashboard/app.py"
    ).read_text()
    i_deals = src.index("_query = select(CrmDeal).where(CrmDeal.org_id == org_id)")
    i_flag = src.index("if crm_enabled:", i_deals)
    assert i_deals < i_flag, "the deals query must not be inside the crm_enabled branch"


def test_cal_booking_is_granted_to_both_sales_templates():
    """The cal_booking tool was registered and the Cal.com stack self-hosted,
    but no sales template granted it, so it was reachable by nobody."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "aios/templates"
    for name in ("sdr.py", "closer.py"):
        assert "cal_booking" in (root / name).read_text(), f"{name} lacks cal_booking"


def test_google_calendar_card_only_exists_in_settings():
    """Asked twice, so pin it: the Google Calendar connect card belongs to the
    settings page and must not reappear on the dashboard home."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "aios/dashboard/templates"
    hits = [
        p.name for p in root.glob("*.html")
        if "google/calendar/login" in p.read_text() or "Google Calendar — Agendamento" in p.read_text()
    ]
    assert hits == ["settings.html"], f"calendar card leaked into {hits}"
