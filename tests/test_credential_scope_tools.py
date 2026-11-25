"""Tools must check credential scope before decrypting or sending a request.

All HTTP is faked: a deny must leave no request behind, and an allow must send
only the decrypted dummy token, never the inline key the caller also supplied.
"""

import contextlib
import json

import pytest
import pytest_asyncio

from aios.db.models import Agent, Credential, CredentialScope
from aios.tools.http_request import HttpRequestTool
from aios.tools.hubspot import HubSpotTool
from aios.tools.pipedrive import PipedriveTool
from aios.tools.rdstation import RDStationTool

_TOKEN = "dummy-token"
_INLINE = "inline-secret"
_DEC_CALLS = []

_CASES = [
    ("http_request", HttpRequestTool, {"url": "https://example.com/x", "auth_type": "api_key", "auth_value": _INLINE}),
    ("hubspot", HubSpotTool, {"action": "search_contact", "email": "a@b.com", "api_key": _INLINE}),
    ("pipedrive", PipedriveTool, {"action": "create_person", "name": "A", "email": "a@b.com", "api_token": _INLINE}),
    ("rdstation", RDStationTool, {"action": "create_lead", "email": "a@b.com", "api_key": _INLINE}),
]


@pytest_asyncio.fixture
async def seed(test_session, test_org):
    agent = Agent(org_id=test_org.id, name="scope-agent")
    cred = Credential(org_id=test_org.id, name="key", cred_type="bearer", data_enc="")
    test_session.add_all([agent, cred])
    await test_session.commit()
    await test_session.refresh(agent)
    await test_session.refresh(cred)
    return test_org, agent, cred


@contextlib.asynccontextmanager
async def _session(sess):
    yield sess


def _fake_decrypt(data_enc):
    _DEC_CALLS.append(data_enc)
    return json.dumps({"token": _TOKEN})


class _FakeResponse:
    status_code = 200
    headers = {}
    text = "{}"

    def json(self):
        return {}


class _FakeClient:
    calls = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, **kw):
        _FakeClient.calls.append(
            {"method": method, "url": url, "headers": kw.get("headers") or {}, "params": kw.get("params") or {}, "json": kw.get("json") or {}}
        )
        return _FakeResponse()

    async def post(self, url, **kw):
        return await self.request("POST", url, **kw)

    async def patch(self, url, **kw):
        return await self.request("PATCH", url, **kw)


@pytest.fixture(autouse=True)
def _patch_runtime(monkeypatch, test_session):
    _FakeClient.calls = []
    _DEC_CALLS.clear()
    monkeypatch.setattr("aios.db.engine.async_session", lambda: _session(test_session))
    monkeypatch.setattr("aios.tools.http_request.check_url", lambda *a, **k: None)
    monkeypatch.setattr("aios.core.secrets.decrypt_secret", _fake_decrypt)
    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)


def _tool(cls, org_id, agent_id):
    tool = cls()
    tool._org_id = org_id
    tool._agent_id = agent_id
    return tool


def _assert_sent(name, *, token=_TOKEN, inline=None):
    assert len(_FakeClient.calls) == 1, name
    blob = json.dumps(_FakeClient.calls[0])
    assert token in blob, name
    if inline:
        assert inline not in blob, name


def _assert_denied(name, res):
    assert "error" in res, name
    if name == "http_request":
        assert res["status"] == 0
        assert res["error"] == "credential access denied"
    else:
        assert "não autorizada" in res["error"], name


async def _add_scope(sess, cred, org_id, scope_type, scope_id):
    sess.add(
        CredentialScope(
            org_id=org_id,
            credential_id=cred.id,
            scope_type=scope_type,
            scope_id=scope_id,
        )
    )
    await sess.commit()


@pytest.mark.parametrize("name, cls, kwargs", _CASES)
async def test_no_credential_id_keeps_inline_auth(seed, name, cls, kwargs):
    org, agent, _ = seed
    res = await _tool(cls, org.id, agent.id).run(**kwargs)
    assert "error" not in res, name
    assert _DEC_CALLS == []
    _assert_sent(name, token=_INLINE)


@pytest.mark.parametrize("name, cls, kwargs", _CASES)
async def test_legacy_no_scope_allows(seed, name, cls, kwargs):
    org, agent, cred = seed
    cred.data_enc = "dummy-enc"  # autoflush writes it; no real encrypted secret
    res = await _tool(cls, org.id, agent.id).run(credential_id=cred.id, **kwargs)
    assert "error" not in res, name
    assert _DEC_CALLS == ["dummy-enc"]
    _assert_sent(name, inline=_INLINE)


@pytest.mark.parametrize("name, cls, kwargs", _CASES)
async def test_agent_scope_allows(test_session, seed, name, cls, kwargs):
    org, agent, cred = seed
    cred_id, agent_id = cred.id, agent.id
    await _add_scope(test_session, cred, org.id, "agent", agent_id)
    cred.data_enc = "dummy-enc"
    res = await _tool(cls, org.id, agent_id).run(credential_id=cred_id, **kwargs)
    assert "error" not in res, name
    assert _DEC_CALLS == ["dummy-enc"]
    _assert_sent(name, inline=_INLINE)


@pytest.mark.parametrize("name, cls, kwargs", _CASES)
async def test_tool_scope_allows(test_session, seed, name, cls, kwargs):
    org, agent, cred = seed
    cred_id, agent_id = cred.id, agent.id
    await _add_scope(test_session, cred, org.id, "tool", name)
    cred.data_enc = "dummy-enc"
    res = await _tool(cls, org.id, agent_id).run(credential_id=cred_id, **kwargs)
    assert "error" not in res, name
    assert _DEC_CALLS == ["dummy-enc"]
    _assert_sent(name, inline=_INLINE)


@pytest.mark.parametrize("name, cls, kwargs", _CASES)
async def test_scope_mismatch_denies_without_fallthrough(test_session, seed, name, cls, kwargs):
    org, agent, cred = seed
    cred_id, agent_id = cred.id, agent.id
    await _add_scope(test_session, cred, org.id, "agent", "other-agent")
    res = await _tool(cls, org.id, agent_id).run(credential_id=cred_id, **kwargs)
    _assert_denied(name, res)
    assert _DEC_CALLS == [], name
    assert _FakeClient.calls == [], name


@pytest.mark.parametrize("name, cls, kwargs", _CASES)
async def test_cross_org_denies(seed, second_org, name, cls, kwargs):
    org, agent, cred = seed
    res = await _tool(cls, second_org.id, agent.id).run(credential_id=cred.id, **kwargs)
    _assert_denied(name, res)
    assert _DEC_CALLS == [], name
    assert _FakeClient.calls == [], name


@pytest.mark.parametrize("name, cls, kwargs", _CASES)
async def test_resolver_exception_fails_closed(monkeypatch, seed, name, cls, kwargs):
    org, agent, cred = seed

    async def boom(*a, **k):
        raise RuntimeError("resolver down")

    monkeypatch.setattr("aios.core.credential_scope.resolve_scoped_credential", boom)
    res = await _tool(cls, org.id, agent.id).run(credential_id=cred.id, **kwargs)
    _assert_denied(name, res)
    assert _DEC_CALLS == [], name
    assert _FakeClient.calls == [], name
