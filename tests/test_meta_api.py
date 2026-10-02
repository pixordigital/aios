"""Tests for the Meta Graph client.

The point of these is the safety properties, not the happy path: retry policy,
timeouts, appsecret_proof, and the refusal to resolve a WABA implicitly.
"""

import httpx
import pytest

from aios.core.meta_api import (
    ERR_DUPLICATE_NAME,
    ERR_MISSING_PERMISSION,
    ERR_RATE_LIMITED,
    GRAPH_VERSION,
    MetaAPIError,
    MetaWhatsAppClient,
    TemplateComponents,
    appsecret_proof,
)


class FakeTransport(httpx.AsyncBaseTransport):
    """Records every request and replays a scripted list of responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        resp = self.responses.pop(0) if self.responses else {"status": 200, "json": {}}
        status = resp.get("status", 200)
        return httpx.Response(status, json=resp.get("json", {}), request=request)


def client(responses, **kw):
    transport = FakeTransport(responses)
    c = MetaWhatsAppClient(
        waba_id="WABA123",
        access_token="TOKEN",
        app_secret="SECRET",
        client=httpx.AsyncClient(transport=transport),
        **kw,
    )
    return c, transport


# ── construction safety ──────────────────────────────────────────────────

def test_requires_waba_id():
    with pytest.raises(ValueError):
        MetaWhatsAppClient(waba_id="", access_token="T")


def test_requires_access_token():
    with pytest.raises(ValueError):
        MetaWhatsAppClient(waba_id="W", access_token="")


def test_from_connection_refuses_incomplete_row():
    """Must never fall back to some other account's WABA."""

    class Conn:
        waba_id = ""
        access_token_enc = ""

    with pytest.raises(MetaAPIError):
        MetaWhatsAppClient.from_connection(Conn(), app_secret="S")


def test_from_connection_refuses_missing_token():
    class Conn:
        waba_id = "WABA1"
        access_token_enc = ""

    with pytest.raises(MetaAPIError):
        MetaWhatsAppClient.from_connection(Conn(), app_secret="S")


def test_no_default_waba_resolver_exists():
    """A global WABA lookup would reintroduce cross-tenant access."""
    from aios.core import meta_api
    for name in dir(meta_api):
        assert not name.startswith("get_default_waba")
        assert not name.startswith("resolve_waba")


# ── request shape ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_appsecret_proof_sent_on_every_call():
    c, t = client([{"status": 200, "json": {"data": []}}])
    await c.list_templates()
    await c.get_template("999")
    assert len(t.requests) == 2
    for r in t.requests:
        assert r.headers["appsecret_proof"] == appsecret_proof("SECRET", "TOKEN")


@pytest.mark.asyncio
async def test_bearer_token_and_pinned_version():
    c, t = client([{"status": 200, "json": {"data": []}}])
    await c.list_templates()
    r = t.requests[0]
    assert r.headers["authorization"] == "Bearer TOKEN"
    assert f"/{GRAPH_VERSION}/" in str(r.url)


@pytest.mark.asyncio
async def test_waba_id_is_in_the_path():
    c, t = client([{"status": 200, "json": {"data": []}}])
    await c.list_templates()
    assert "/WABA123/message_templates" in str(t.requests[0].url)


@pytest.mark.asyncio
async def test_timeout_is_always_set():
    c, t = client([{"status": 200, "json": {"data": []}}])
    await c.list_templates()
    assert c.timeout and c.timeout > 0


# ── retry policy ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retries_on_rate_limit():
    c, t = client([
        {"status": 400, "json": {"error": {"code": ERR_RATE_LIMITED, "message": "slow down"}}},
        {"status": 200, "json": {"data": [{"id": "1"}]}},
    ])
    res = await c.list_templates()
    assert res == [{"id": "1"}]
    assert len(t.requests) == 2


@pytest.mark.asyncio
async def test_retries_on_5xx():
    c, t = client([
        {"status": 503, "json": {}},
        {"status": 200, "json": {"data": []}},
    ])
    await c.list_templates()
    assert len(t.requests) == 2


@pytest.mark.asyncio
async def test_does_not_retry_permission_errors():
    """Retrying a 4xx wastes quota that protects the tenant's quality rating."""
    c, t = client([
        {"status": 400, "json": {"error": {"code": ERR_MISSING_PERMISSION, "message": "no perms"}}},
    ])
    with pytest.raises(MetaAPIError) as e:
        await c.list_templates()
    assert e.value.code == ERR_MISSING_PERMISSION
    assert len(t.requests) == 1, "must not retry a permission error"


@pytest.mark.asyncio
async def test_does_not_retry_duplicate_name():
    c, t = client([
        {"status": 400, "json": {"error": {"code": ERR_DUPLICATE_NAME, "message": "dup"}}},
    ])
    with pytest.raises(MetaAPIError) as e:
        await c.create_template(
            name="x", language="pt_BR", category="UTILITY", components=TemplateComponents(body="ola")
        )
    assert e.value.code == ERR_DUPLICATE_NAME
    assert len(t.requests) == 1


@pytest.mark.asyncio
async def test_gives_up_after_max_attempts():
    c, t = client([{"status": 503, "json": {}}] * 6)
    with pytest.raises(MetaAPIError):
        await c.list_templates()
    assert len(t.requests) <= 4


@pytest.mark.asyncio
async def test_retries_transport_errors():
    class Flaky(httpx.AsyncBaseTransport):
        def __init__(self):
            self.n = 0

        async def handle_async_request(self, request):
            self.n += 1
            if self.n == 1:
                raise httpx.ConnectError("boom", request=request)
            return httpx.Response(200, json={"data": []}, request=request)

    t = Flaky()
    c = MetaWhatsAppClient("W", "T", client=httpx.AsyncClient(transport=t))
    assert await c.list_templates() == []
    assert t.n == 2


# ── error surfacing ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_error_carries_code_and_actionable_hint():
    c, t = client([
        {"status": 400, "json": {"error": {"code": ERR_MISSING_PERMISSION, "message": "no perms"}}},
    ])
    with pytest.raises(MetaAPIError) as e:
        await c.list_templates()
    assert e.value.code == ERR_MISSING_PERMISSION
    assert "whatsapp_business_management" in (e.value.hint or "")
    assert e.value.raw_message == "no perms"


@pytest.mark.asyncio
async def test_subcode_is_preserved():
    c, t = client([
        {"status": 400, "json": {"error": {"code": 10, "subcode": 2388024, "message": "exists"}}},
    ])
    with pytest.raises(MetaAPIError) as e:
        await c.list_templates()
    assert "2388024" in e.value.raw_message


# ── payload shape ────────────────────────────────────────────────────────

def test_allow_category_change_defaults_on():
    """Meta documents this as preventing miscategorisation rejection."""
    import inspect
    sig = inspect.signature(MetaWhatsAppClient.create_template)
    assert sig.parameters["allow_category_change"].default is True


@pytest.mark.asyncio
async def test_create_sends_expected_payload():
    c, t = client([{"status": 200, "json": {"id": "55"}}])
    import json
    await c.create_template(
        name="lembrete_consulta",
        language="pt_BR",
        category="UTILITY",
        components=TemplateComponents(
            header_text="Aviso",
            body="Ola {{1}}, sua consulta e {{2}}.",
            footer="Obrigado",
            examples={"1": "Joao", "2": "12/03"},
        ),
    )
    body = json.loads(t.requests[0].content)
    assert body["name"] == "lembrete_consulta"
    assert body["language"] == "pt_BR"
    assert body["allow_category_change"] is True
    types = [c_["type"] for c_ in body["components"]]
    assert types == ["HEADER", "BODY", "FOOTER"]
    body_comp = next(c_ for c_ in body["components"] if c_["type"] == "BODY")
    assert body_comp["example"] == {"1": ["Joao"], "2": ["12/03"]}


@pytest.mark.asyncio
async def test_examples_omitted_when_empty():
    """Sending an empty example object is worse than omitting it."""
    import json
    c, t = client([{"status": 200, "json": {"id": "1"}}])
    await c.create_template(
        name="x", language="pt_BR", category="UTILITY",
        components=TemplateComponents(body="ola"),
    )
    body = json.loads(t.requests[0].content)
    assert "example" not in body["components"][0]


@pytest.mark.asyncio
async def test_text_only_skips_empty_header():
    import json
    c, t = client([{"status": 200, "json": {"id": "1"}}])
    await c.create_template(
        name="x", language="pt_BR", category="UTILITY",
        components=TemplateComponents(body="ola", header_text=""),
    )
    body = json.loads(t.requests[0].content)
    assert [c_["type"] for c_ in body["components"]] == ["BODY"]