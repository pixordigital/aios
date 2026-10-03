"""Single-operator lockdown: only AIOS_LOGIN_ALLOWLIST may authenticate.

Each test names the bypass it closes. The allowlist is enforced twice —
at token issuance AND on every authenticated request — so removing an
address (or never having it listed) kills existing sessions immediately,
not at token expiry.
"""

import contextlib
import types

import pytest
from fastapi import HTTPException

from aios.api import auth as auth_mod
from aios.config import settings

LISTED = "pixordigital@gmail.com"
OTHER = "intruder@example.com"


def _user(email, **kw):
    d = {
        "id": "u1", "email": email,
        "hashed_password": auth_mod._hash_password("correct-horse-42"),
        "org_id": "o1", "role": "admin", "email_verified": True,
        "totp_enabled": False, "totp_secret": None,
        "totp_backup_codes": None,
    }
    d.update(kw)
    return types.SimpleNamespace(**d)


class _Result:
    def __init__(self, user=None):
        self._user = user

    def scalar_one_or_none(self):
        return self._user

    def first(self):
        return None  # blacklist table: no hit


class _DB:
    """Fake backend. `explode=True` proves the code path never touched the DB."""

    def __init__(self, user=None, explode=False):
        self._user = user
        self.explode = explode
        self.added = []

    async def execute(self, *a, **k):
        assert not self.explode, "DB was touched on a path that must reject first"
        return _Result(self._user)

    async def get(self, model, ident):
        assert not self.explode, "DB was touched on a path that must reject first"
        return self._user

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


def _req(ip="9.9.9.9"):
    return types.SimpleNamespace(client=types.SimpleNamespace(host=ip))


def _allow(monkeypatch, value=LISTED):
    monkeypatch.setattr(settings, "login_allowlist", value)


# ─── parsing ──────────────────────────────────────────────────────────────

def test_allowlist_parsing_is_case_and_space_tolerant(monkeypatch):
    _allow(monkeypatch, "  PixorDigital@Gmail.Com ; other@x.com,")
    assert auth_mod._is_login_allowed("pixordigital@gmail.com")
    assert auth_mod._is_login_allowed("OTHER@x.com")
    assert not auth_mod._is_login_allowed("intruder@example.com")


def test_empty_allowlist_is_open_but_never_trusted(monkeypatch):
    """Unconfigured = legacy behavior for the gate, but _is_allowlisted must
    still be False for everyone — it drives trust decisions like skipping the
    email-verification gate."""
    _allow(monkeypatch, "")
    assert auth_mod._is_login_allowed("anyone@example.com")
    assert not auth_mod._is_allowlisted("anyone@example.com")


# ─── password login ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_listed_login_succeeds(monkeypatch):
    from aios.schemas import LoginRequest

    _allow(monkeypatch)
    body = LoginRequest(email=LISTED, password="correct-horse-42")
    out = await auth_mod.login(_req(), body, _DB(_user(LISTED)))
    assert out.user_id == "u1" and out.org_id == "o1"


@pytest.mark.asyncio
async def test_nonlisted_login_rejected_with_generic_message(monkeypatch):
    """Same 401 text as a wrong password: indistinguishable, so the response
    reveals neither allowlist membership nor account existence."""
    from aios.schemas import LoginRequest

    _allow(monkeypatch)
    body = LoginRequest(email=OTHER, password="correct-horse-42")  # right password
    with pytest.raises(HTTPException) as e:
        await auth_mod.login(_req(), body, _DB(_user(OTHER)))
    assert e.value.status_code == 401
    assert e.value.detail == "E-mail ou senha inválidos"


@pytest.mark.asyncio
async def test_allowlisted_unverified_user_not_blocked_by_beta_gate(monkeypatch):
    """Without this the verification gate (meant for self-serve signups) would
    lock out the very operator account the allowlist was built for."""
    from aios.schemas import LoginRequest

    _allow(monkeypatch)
    monkeypatch.setattr(settings, "registration_enabled", False)
    body = LoginRequest(email=LISTED, password="correct-horse-42")
    out = await auth_mod.login(_req(), body, _DB(_user(LISTED, email_verified=False)))
    assert out.user_id == "u1"


# ─── refresh ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_rejected_for_nonlisted(monkeypatch):
    _allow(monkeypatch)
    token = auth_mod._create_refresh_token("u1")
    with pytest.raises(HTTPException) as e:
        await auth_mod.refresh_token(_req(), {"refresh_token": token}, _DB(_user(OTHER)))
    assert e.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_allowed_for_listed(monkeypatch):
    _allow(monkeypatch)
    token = auth_mod._create_refresh_token("u1")
    out = await auth_mod.refresh_token(_req(), {"refresh_token": token}, _DB(_user(LISTED)))
    assert out.user_id == "u1"


# ─── OAuth ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_oauth_rejected_before_any_db_touch(monkeypatch):
    """Any Google/GitHub identity with a non-listed email gets nothing — no
    token, no account row, no OAuth link row."""
    _allow(monkeypatch)
    with pytest.raises(HTTPException) as e:
        await auth_mod._oauth_login_or_register(
            _DB(explode=True), "google", "gid-1", OTHER, "Intruder")
    assert e.value.status_code == 403


# ─── registration ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_register_gated_by_allowlist(monkeypatch):
    from aios.schemas import RegisterRequest

    _allow(monkeypatch)
    monkeypatch.setattr(settings, "registration_enabled", True)
    body = RegisterRequest(email=OTHER, password="correct-horse-42", org_name="Evil")
    with pytest.raises(HTTPException) as e:
        await auth_mod.register(_req(), body, _DB())
    assert e.value.status_code == 403


# ─── password reset / verify ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_forgot_password_sends_nothing_for_nonlisted(monkeypatch):
    _allow(monkeypatch)
    sent = []
    monkeypatch.setattr(auth_mod, "_send_email", _recorder(sent))
    out = await auth_mod.forgot_password(OTHER, _DB(_user(OTHER)))
    assert out["message"].startswith("Se o e-mail existir")
    assert sent == [], "reset email left the server for a non-listed address"


@pytest.mark.asyncio
async def test_forgot_password_sends_for_listed(monkeypatch):
    _allow(monkeypatch)
    sent = []
    monkeypatch.setattr(auth_mod, "_send_email", _recorder(sent))
    await auth_mod.forgot_password(LISTED, _DB(_user(LISTED)))
    assert sent == [LISTED]


@pytest.mark.asyncio
async def test_verify_and_reset_rejected_for_nonlisted(monkeypatch):
    _allow(monkeypatch)
    vt = auth_mod._create_email_token("u1", "email_verify")
    with pytest.raises(HTTPException):
        await auth_mod.verify_email(vt, _DB(_user(OTHER)))
    rt = auth_mod._create_email_token("u1", "password_reset")
    body = auth_mod.ResetPasswordRequest(token=rt, new_password="new-horse-43")
    with pytest.raises(HTTPException):
        await auth_mod.reset_password(body, _DB(_user(OTHER)))


def _recorder(sent):
    async def _send(to, subject, body):
        sent.append(to)
        return True
    return _send


# ─── session verification (kills existing sessions) ───────────────────────

@pytest.mark.asyncio
async def test_bearer_token_rejected_for_nonlisted(monkeypatch):
    from aios.api import deps as deps_mod

    _allow(monkeypatch)
    token = auth_mod._create_access_token("u1", "o1")
    with pytest.raises(HTTPException) as e:
        await deps_mod.get_current_user(
            None, _DB(_user(OTHER)), authorization=f"Bearer {token}")
    assert e.value.status_code == 401


@pytest.mark.asyncio
async def test_bearer_token_accepted_for_listed(monkeypatch):
    from aios.api import deps as deps_mod

    _allow(monkeypatch)
    token = auth_mod._create_access_token("u1", "o1")
    user = await deps_mod.get_current_user(
        None, _DB(_user(LISTED)), authorization=f"Bearer {token}")
    assert user.id == "u1"


@pytest.mark.asyncio
async def test_dashboard_cookie_rejected_for_nonlisted(monkeypatch):
    from aios.api import deps as deps_mod
    from aios.db.backend import get_db_backend

    _allow(monkeypatch)
    token = auth_mod._create_access_token("u1", "o1")

    async def _gen():
        yield _DB(_user(OTHER))

    req = types.SimpleNamespace(
        cookies={deps_mod.COOKIE_NAME: token},
        app=types.SimpleNamespace(dependency_overrides={get_db_backend: _gen}),
    )
    assert await deps_mod.get_dashboard_user(req) is None


# ─── websocket ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ws_rejects_refresh_tokens(monkeypatch):
    """A stolen 30-day refresh token previously authenticated a socket exactly
    like a 60-minute access token. Now only access tokens work."""
    from aios.api import ws as ws_mod

    _allow(monkeypatch)
    monkeypatch.setattr(ws_mod, "db_session", _session(_DB(_user(LISTED))))
    ws = types.SimpleNamespace(
        query_params={"token": auth_mod._create_refresh_token("u1")})
    assert await ws_mod._auth_ws(ws) is None


@pytest.mark.asyncio
async def test_ws_rejects_nonlisted_access_token(monkeypatch):
    from aios.api import ws as ws_mod

    _allow(monkeypatch)
    monkeypatch.setattr(ws_mod, "db_session", _session(_DB(_user(OTHER))))
    ws = types.SimpleNamespace(
        query_params={"token": auth_mod._create_access_token("u1", "o1")})
    assert await ws_mod._auth_ws(ws) is None


@pytest.mark.asyncio
async def test_ws_accepts_listed_access_token(monkeypatch):
    from aios.api import ws as ws_mod

    _allow(monkeypatch)
    monkeypatch.setattr(ws_mod, "db_session", _session(_DB(_user(LISTED))))
    ws = types.SimpleNamespace(
        query_params={"token": auth_mod._create_access_token("u1", "o1")})
    user = await ws_mod._auth_ws(ws)
    assert user and user.id == "u1"


def _session(db):
    @contextlib.asynccontextmanager
    async def _cm():
        yield db
    return _cm


# ─── dashboard login ──────────────────────────────────────────────────────

def _dash_req():
    return types.SimpleNamespace(
        client=types.SimpleNamespace(host="9.9.9.9"),
        url=types.SimpleNamespace(scheme="https"),
        headers={}, state=None,
    )


@pytest.mark.asyncio
async def test_dashboard_login_rejects_nonlisted_without_cookie(monkeypatch):
    import aios.dashboard.app as app_mod

    _allow(monkeypatch)
    monkeypatch.setattr(app_mod, "db_session", _session(_DB(_user(OTHER, role="admin"))))
    monkeypatch.setattr(app_mod, "login_page", _login_page_marker())

    resp = await app_mod.login_action(_dash_req(), OTHER, "correct-horse-42")
    assert resp.status_code == 200  # re-rendered login page, not a redirect
    assert "set-cookie" not in {k.lower() for k in resp.headers}


@pytest.mark.asyncio
async def test_dashboard_login_issues_cookie_for_listed(monkeypatch):
    import aios.dashboard.app as app_mod

    _allow(monkeypatch)
    monkeypatch.setattr(app_mod, "db_session", _session(_DB(_user(LISTED, role="admin"))))
    resp = await app_mod.login_action(_dash_req(), LISTED, "correct-horse-42")
    assert resp.status_code == 303
    assert "aios_token" in resp.headers.get("set-cookie", "")


def _login_page_marker():
    from fastapi.responses import HTMLResponse

    async def _fake(request, error=""):
        return HTMLResponse("login page: " + error)
    return _fake
