"""Evolution integration tests.

Two production-blocking bugs:

1. `_validate_url()` applied the SSRF private-IP guard to the Evolution server
   URL. Evolution is a first-party service on the internal Docker network
   (http://evolution:8080), so `_is_private("evolution")` is True and both send
   paths returned None before sending anything — no WhatsApp message could ever
   leave the system.

2. The webhook required an `x-evolution-signature` header and compared it to
   HMAC(api_key, canonical_body). Evolution API does not sign request bodies;
   its `webhookAuth` sends a static shared secret in a header. Every inbound
   message was dropped with a log line nobody watched.
"""

import httpx
import pytest

from aios.api.evolution_webhook import _AUTH_HEADERS, _verify_evolution_sig, _verify_request
from aios.channels.evolution import EvolutionChannel


class _Conn:
    def __init__(self, config):
        self.config = config
        self.channel_type = "evolution"


class _Req:
    """Minimal Request stand-in."""

    def __init__(self, headers, body=None):
        self.headers = {k.lower(): v for k, v in headers.items()}
        import types

        self.state = types.SimpleNamespace(aios_body=body or {})


def _ch(**cfg):
    base = {"server_url": "http://evolution:8080", "instance": "i1", "api_key": "k"}
    base.update(cfg)
    return EvolutionChannel(connection=_Conn(base))


class TestEvolutionUrlValidation:
    @pytest.mark.asyncio
    async def test_internal_evolution_url_is_allowed(self):
        """The regression: internal Docker host must pass."""
        assert await _ch()._validate_url() is True

    @pytest.mark.asyncio
    async def test_https_public_allowed(self):
        assert await _ch(server_url="https://evo.example.com")._validate_url() is True

    @pytest.mark.asyncio
    async def test_non_http_scheme_blocked(self):
        assert await _ch(server_url="ftp://evolution:8080")._validate_url() is False

    @pytest.mark.asyncio
    async def test_missing_host_blocked(self):
        assert await _ch(server_url="http://")._validate_url() is False

    @pytest.mark.asyncio
    async def test_embedded_credentials_blocked(self):
        assert await _ch(server_url="http://user:pw@evolution:8080")._validate_url() is False


class TestEvolutionWebhookAuth:
    def test_shared_secret_header_accepted(self):
        assert _verify_request(_Req({"x-webhook-auth": "secret"}), "secret") is True

    def test_all_supported_headers(self):
        for h in _AUTH_HEADERS:
            if h == "x-evolution-signature":
                continue  # HMAC path, covered separately
            assert _verify_request(_Req({h: "secret"}), "secret") is True, h

    def test_wrong_secret_rejected(self):
        assert _verify_request(_Req({"x-webhook-auth": "nope"}), "secret") is False

    def test_missing_header_rejected(self):
        assert _verify_request(_Req({}), "secret") is False

    def test_empty_api_key_rejects(self):
        assert _verify_request(_Req({"x-webhook-auth": ""}), "") is False

    def test_hmac_body_path_still_works(self):
        import hashlib
        import hmac
        import json

        body = {"event": "messages.upsert", "data": {}}
        raw = json.dumps(body, separators=(",", ":"), sort_keys=True)
        sig = hmac.new(b"k", raw.encode(), hashlib.sha256).hexdigest()
        req = _Req({"x-evolution-signature": sig}, body)
        assert _verify_request(req, "k") is True
        assert _verify_evolution_sig(sig, body, "k") is True

    def test_hmac_wrong_key_rejected(self):
        import hashlib
        import hmac
        import json

        body = {"a": 1}
        raw = json.dumps(body, separators=(",", ":"), sort_keys=True)
        sig = hmac.new(b"other", raw.encode(), hashlib.sha256).hexdigest()
        assert _verify_request(_Req({"x-evolution-signature": sig}, body), "k") is False


class TestEvolutionInstanceLimit:
    def test_org_plan_read_from_extra_data(self):
        """Regression: Organization has no .plan column; it lives in extra_data.

        Reading org.plan raised AttributeError, which the surrounding
        `except Exception` swallowed, so the instance limit never applied.
        """
        from aios.db.models import Organization

        assert not hasattr(Organization, "plan")
        assert "extra_data" in {c.name for c in Organization.__table__.columns}

    def test_no_guarded_plan_attribute_access(self):
        import inspect
        import io
        import tokenize

        from aios.channels.evolution import EvolutionChannel as EC

        src = inspect.getsource(EC._check_instance_limit)
        code_only = []
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type not in (tokenize.COMMENT, tokenize.STRING):
                code_only.append(tok)
        code = tokenize.untokenize(code_only)
        if isinstance(code, bytes):
            code = code.decode()
        assert "org.plan" not in code, "must read plan from extra_data"
        assert "extra_data" in code


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)[:200]

    def json(self):
        return self._payload


class _FakeClient:
    """Records calls; returns queued responses keyed by URL substring."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def _match(self, url):
        for frag, resp in self.responses:
            if frag in url:
                return resp
        return _FakeResp(404, {"error": f"no stub for {url}"})

    async def get(self, url, **kw):
        self.calls.append(("GET", url, kw.get("json")))
        return self._match(url)

    async def post(self, url, **kw):
        self.calls.append(("POST", url, kw.get("json")))
        return self._match(url)


class TestProviderSwitch:
    """The channel form writes config['provider'] but never told Evolution.

    Flipping the selector changed the outbound send path while the instance
    kept WHATSAPP-BAILEYS, so Meta payloads went to a Baileys instance.
    """

    def _patch(self, monkeypatch, responses):
        client = _FakeClient(responses)
        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: client)
        return client

    @pytest.mark.asyncio
    async def test_meta_requires_credentials(self, monkeypatch):
        ch = _ch(provider="meta")
        res = await ch.reconcile_provider()
        assert res["ok"] is False
        assert res["action"] == "add_credentials"
        assert "WABA ID" in res["message"]

    @pytest.mark.asyncio
    async def test_meta_creates_separate_instance_with_credentials(self, monkeypatch):
        client = self._patch(monkeypatch, [
            ("fetchInstances", _FakeResp(200, [])),
            ("/instance/create", _FakeResp(201, {"instance": {}})),
            ("/webhook/set/", _FakeResp(201, {"ok": True})),
        ])
        ch = _ch(provider="meta", meta_token="T", meta_phone_id="1555", meta_waba_id="999")
        res = await ch.reconcile_provider()
        assert res["ok"] is True
        # must not clobber the paired baileys instance
        assert res["instance"] == "i1-meta"
        create = [c for c in client.calls if c[0] == "POST" and "/instance/create" in c[1]][0]
        assert create[2]["integration"] == "WHATSAPP-BUSINESS"
        assert create[2]["token"] == "T"
        assert create[2]["number"] == "1555"
        assert create[2]["instanceId"] == "999"

    @pytest.mark.asyncio
    async def test_switch_back_reuses_paired_baileys_instance(self, monkeypatch):
        client = self._patch(monkeypatch, [
            ("fetchInstances", _FakeResp(200, [
                {"name": "i1", "integration": "WHATSAPP-BAILEYS", "connectionStatus": "open"},
            ])),
            ("/webhook/set/", _FakeResp(201, {"ok": True})),
        ])
        ch = _ch(provider="baileys")
        res = await ch.reconcile_provider()
        assert res["ok"] is True
        assert res["action"] == "ready"
        assert res["instance"] == "i1"
        assert not [c for c in client.calls if "/instance/create" in c[1]]

    @pytest.mark.asyncio
    async def test_asks_for_qr_when_baileys_not_connected(self, monkeypatch):
        self._patch(monkeypatch, [
            ("fetchInstances", _FakeResp(200, [
                {"name": "i1", "integration": "WHATSAPP-BAILEYS", "connectionStatus": "close"},
            ])),
            ("/webhook/set/", _FakeResp(201, {"ok": True})),
        ])
        res = await _ch(provider="baileys").reconcile_provider()
        assert res["action"] == "scan_qr"

    @pytest.mark.asyncio
    async def test_recreates_when_name_exists_with_wrong_integration(self, monkeypatch):
        client = self._patch(monkeypatch, [
            ("fetchInstances", _FakeResp(200, [
                {"name": "i1-meta", "integration": "WHATSAPP-BAILEYS", "connectionStatus": "open"},
            ])),
            ("/instance/create", _FakeResp(201, {"instance": {}})),
            ("/webhook/set/", _FakeResp(201, {"ok": True})),
        ])
        ch = _ch(provider="meta", meta_token="T", meta_phone_id="1", meta_waba_id="2")
        res = await ch.reconcile_provider()
        assert res["ok"] is True
        assert [c for c in client.calls if "/instance/create" in c[1]]

    @pytest.mark.asyncio
    async def test_webhook_secret_goes_in_headers_not_webhookauth(self, monkeypatch):
        client = self._patch(monkeypatch, [
            ("fetchInstances", _FakeResp(200, [])),
            ("/instance/create", _FakeResp(201, {"instance": {}})),
            ("/webhook/set/", _FakeResp(201, {"ok": True})),
        ])
        await _ch(provider="baileys").reconcile_provider()
        hook = [c for c in client.calls if "/webhook/set/" in c[1]][0]
        wh = hook[2]["webhook"]
        # Evolution drops webhookAuth silently; only headers survive.
        assert "webhookAuth" not in wh
        assert wh["headers"]["x-webhook-auth"] == "k"
        assert wh["url"].endswith("/i1")

    @pytest.mark.asyncio
    async def test_reports_webhook_failure_even_when_instance_ok(self, monkeypatch):
        self._patch(monkeypatch, [
            ("fetchInstances", _FakeResp(200, [])),
            ("/instance/create", _FakeResp(201, {"instance": {}})),
            ("/webhook/set/", _FakeResp(500, {"error": "boom"})),
        ])
        res = await _ch(provider="baileys").reconcile_provider()
        assert res["ok"] is False
        assert "webhook" in res["message"]


class TestBanSignalWiring:
    def test_humanize_delay_is_not_awaited(self):
        """Regression: every Baileys send was failing silently.

        `await humanize_delay(...)` on a sync function raises TypeError, and the
        surrounding `except Exception` turned it into `return None`. No message
        was ever sent, and no error was ever logged as a failure.
        """
        import inspect

        from aios.core.whatsapp_guard import humanize_delay

        assert not inspect.iscoroutinefunction(humanize_delay)
        assert isinstance(humanize_delay("oi"), float)

    def test_no_awaited_sync_guard_helpers_remain(self):
        from pathlib import Path

        src = Path("aios/channels/evolution.py").read_text()
        # strip the comment that documents the old bug
        body = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        for helper in ("humanize_delay", "vary_text", "record_ban_signal"):
            assert f"await {helper}(" not in body, f"{helper} is sync but awaited"
