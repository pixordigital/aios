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
