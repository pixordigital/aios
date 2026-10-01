"""Regression tests for the auth hardening and the SSRF escape hatch.

Two things are pinned here:

1. Login spent no CPU when the email was unknown, so response time revealed
   which addresses are registered. Login now always runs one bcrypt verify.
2. The rate limit was keyed on email alone, so anyone who knew a customer's
   address could lock that account out for the whole window.
3. `allow_private` was a field on the http_request tool input model, which means
   the agent could switch off its own SSRF guard and read cloud metadata.
"""

import asyncio
import inspect

import pytest

from aios.api import auth as auth_mod
from aios.tools.http_request import HttpRequestInput, HttpRequestTool


# ─── login must not leak account existence ────────────────────────────────

@pytest.mark.asyncio
async def test_login_burns_bcrypt_for_unknown_email(monkeypatch):
    """An unknown email still pays the hash cost, so timing matches a bad password."""
    calls = []
    real_verify = auth_mod._verify_password

    def spy(password, stored):
        calls.append(stored)
        return real_verify(password, stored)

    monkeypatch.setattr(auth_mod, "_verify_password", spy)

    class FakeResult:
        def scalar_one_or_none(self):
            return None  # no such user

    class FakeDB:
        async def execute(self, *a, **k):
            return FakeResult()

    db = FakeDB()
    monkeypatch.setattr(auth_mod, "_rate_limit", _noop)

    with pytest.raises(Exception) as exc:
        await auth_mod.login(_FakeRequest(), _LoginBody(), db)
    assert "inválidos" in str(exc.value)
    # verified against the dummy hash, not skipped
    assert calls == [auth_mod._DUMMY_HASH]


@pytest.mark.asyncio
async def test_login_still_rejects_unknown_email(monkeypatch):
    """Sanity: the constant-work change must not turn into an auth bypass."""
    class FakeResult:
        def scalar_one_or_none(self):
            return None

    class FakeDB:
        async def execute(self, *a, **k):
            return FakeResult()

    monkeypatch.setattr(auth_mod, "_rate_limit", _noop)
    with pytest.raises(Exception) as exc:
        await auth_mod.login(_FakeRequest(), _LoginBody(), db=FakeDB())
    assert exc.value.__class__.__name__ == "HTTPException"
    assert getattr(exc.value, "status_code", None) == 401


def test_dummy_hash_is_not_usable_credential():
    """The dummy hash must verify against nothing a caller could supply."""
    assert not auth_mod._verify_password("", auth_mod._DUMMY_HASH)
    assert not auth_mod._verify_password("password", auth_mod._DUMMY_HASH)
    assert auth_mod._DUMMY_HASH.startswith("$2")


# ─── rate limit must not let one caller lock out a customer ───────────────

def test_login_rate_limit_key_includes_client_ip():
    """The login endpoint must key on email AND ip, not email alone."""
    src = inspect.getsource(auth_mod.login)
    assert "request.client" in src, "login must vary the rate-limit key by client IP"
    assert "_rate_limit(f\"" in src or "_rate_limit(f'" in src


@pytest.mark.asyncio
async def test_rate_limit_isolates_two_clients_for_same_email(monkeypatch):
    """Client A exhausting its budget must not lock out client B."""
    monkeypatch.setattr(auth_mod, "_get_redis", _no_redis)
    monkeypatch.setattr(auth_mod, "_login_attempts", {})

    monkeypatch.setattr(auth_mod, "_MAX_LOGIN_ATTEMPTS", 2)
    for _ in range(2):
        await auth_mod._rate_limit("victim@example.com|1.1.1.1")
    with pytest.raises(Exception):
        await auth_mod._rate_limit("victim@example.com|1.1.1.1")

    # different IP, same account -> still allowed
    await auth_mod._rate_limit("victim@example.com|2.2.2.2")


# ─── SSRF guard must not be agent-disablable ──────────────────────────────

def test_allow_private_not_in_agent_visible_schema():
    """The model must not be able to pass allow_private at all."""
    assert "allow_private" not in HttpRequestInput.model_fields


@pytest.mark.asyncio
async def test_agent_cannot_disable_ssrf_guard(monkeypatch):
    """Passing allow_private=True from the model is ignored without the env opt-in."""
    monkeypatch.delenv("AIOS_ALLOW_PRIVATE_HTTP", raising=False)
    res = await HttpRequestTool().run(url="http://169.254.169.254/latest/meta-data/", allow_private=True)
    assert res.get("error") == "private host blocked"


@pytest.mark.asyncio
async def test_cloud_metadata_blocked_by_default():
    res = await HttpRequestTool().run(url="http://169.254.169.254/latest/meta-data/")
    assert res.get("error") == "private host blocked"


@pytest.mark.asyncio
async def test_operator_can_still_opt_in_out_of_band(monkeypatch):
    """The escape hatch survives for internal callers, gated on the env var."""
    monkeypatch.setenv("AIOS_ALLOW_PRIVATE_HTTP", "1")
    from aios.tools.http_request import _operator_allows_private
    assert _operator_allows_private(None) is True


# ─── helpers ──────────────────────────────────────────────────────────────

async def _noop(*a, **k):
    return None


async def _no_redis():
    return None


class _FakeRequest:
    client = None


class _LoginBody:
    email = "nobody@example.com"
    password = "hunter2"
    totp_code = None