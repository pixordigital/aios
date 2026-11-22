"""Regression tests for the auth hardening and the SSRF escape hatch.

Two things are pinned here:

1. Login spent no CPU when the email was unknown, so response time revealed
   which addresses are registered. Login now always runs one bcrypt verify.
2. The rate limit was keyed on email alone, so anyone who knew a customer's
   address could lock that account out for the whole window.
3. `allow_private` was a field on the http_request tool input model, which means
   the agent could switch off its own SSRF guard and read cloud metadata.
"""

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
    assert res.get("error") == "private/internal host blocked: 169.254.169.254"


@pytest.mark.asyncio
async def test_cloud_metadata_blocked_by_default():
    res = await HttpRequestTool().run(url="http://169.254.169.254/latest/meta-data/")
    assert res.get("error") == "private/internal host blocked: 169.254.169.254"


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

# ─── auth failure recording on allowlist/totp ─────────────────────────────

@pytest.mark.asyncio
async def test_verify_email_allowlist_denied_records_failure(monkeypatch):
    calls = []

    async def fake_record(db, **kw):
        calls.append(kw)

    monkeypatch.setattr(auth_mod, "_record_auth_failure_metric", fake_record)
    monkeypatch.setattr(auth_mod, "_verify_jwt_token", lambda token: {"sub": "u1", "purpose": "email_verify"})
    monkeypatch.setattr(auth_mod, "_is_login_allowed", lambda email: False)

    user = type("U", (), {"id": "u1", "org_id": "org1", "email": "a@b.com", "email_verified": False})()

    class FakeDB:
        async def get(self, model, pk):
            return user

    with pytest.raises(Exception) as exc:
        await auth_mod.verify_email(token="tok", db=FakeDB())
    assert getattr(exc.value, "status_code", None) == 400
    assert calls and calls[0]["org_id"] == "org1"
    assert calls[0]["payload"]["reason"] == "allowlist_denied"
    assert calls[0]["payload"]["source"] == "auth.verify_email"


@pytest.mark.asyncio
async def test_reset_password_allowlist_denied_records_failure(monkeypatch):
    calls = []

    async def fake_record(db, **kw):
        calls.append(kw)

    monkeypatch.setattr(auth_mod, "_record_auth_failure_metric", fake_record)
    monkeypatch.setattr(auth_mod, "_verify_jwt_token", lambda token: {"sub": "u1", "purpose": "password_reset"})
    monkeypatch.setattr(auth_mod, "_validate_password", lambda p: None)
    monkeypatch.setattr(auth_mod, "_is_login_allowed", lambda email: False)

    user = type("U", (), {"id": "u1", "org_id": "org1", "email": "a@b.com"})()

    class FakeDB:
        async def get(self, model, pk):
            return user

    body = type("B", (), {"token": "tok", "new_password": "ValidPass123!"})()
    with pytest.raises(Exception) as exc:
        await auth_mod.reset_password(body=body, db=FakeDB())
    assert getattr(exc.value, "status_code", None) == 400
    assert calls and calls[0]["org_id"] == "org1"
    assert calls[0]["payload"]["reason"] == "allowlist_denied"
    assert calls[0]["payload"]["source"] == "auth.reset_password"


@pytest.mark.asyncio
async def test_totp_verify_invalid_code_records_failure(monkeypatch):
    calls = []

    async def fake_record(db, **kw):
        calls.append(kw)

    monkeypatch.setattr(auth_mod, "_record_auth_failure_metric", fake_record)

    user = type(
        "U",
        (),
        {"id": "u1", "org_id": "org1", "totp_secret": "SECRET", "totp_backup_codes": [], "totp_enabled": False},
    )()

    async def fake_get_current_user(request, db):
        return user

    monkeypatch.setattr("aios.api.deps.get_current_user", fake_get_current_user)

    import pyotp

    monkeypatch.setattr(pyotp.TOTP, "verify", lambda self, code, valid_window=1: False)

    class FakeDB:
        async def commit(self):
            return None

    with pytest.raises(Exception) as exc:
        await auth_mod.totp_verify(_FakeRequest(), code="000000", db=FakeDB())
    assert getattr(exc.value, "status_code", None) == 401
    assert calls and calls[0]["org_id"] == "org1"
    assert calls[0]["actor_id"] == "u1"
    assert calls[0]["payload"]["reason"] == "totp_invalid"
    assert calls[0]["payload"]["source"] == "auth.totp_verify"
