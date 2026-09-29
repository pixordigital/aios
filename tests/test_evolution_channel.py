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
