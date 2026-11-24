"""Suite AIOS+ARVO — HMAC cross, events, suite health."""

import os

import pytest
from fastapi.testclient import TestClient

# The sibling checkout is an environment fact, not a constant. CI and fresh
# machines do not have it; skipping there is honest, while a hardcoded path
# that can never exist fails the suite for reasons that have nothing to do
# with the code.
ARVO_REPO = os.environ.get(
    "ARVO_REPO_PATH", "/home/pixor/ai_projects/claude_projects/arvo"
)
needs_arvo = pytest.mark.skipif(
    not os.path.isdir(ARVO_REPO), reason="sibling ARVO checkout not present"
)


def _arvo_auth_path() -> str:
    return os.path.join(ARVO_REPO, "app", "integrations", "aios", "auth.py")


@needs_arvo
def test_suite_imports():
    """Both services importable as suite."""
    import aios.main  # noqa: F401
    import importlib.util
    import pathlib

    arvo_main = pathlib.Path(ARVO_REPO, "app", "main.py")
    assert arvo_main.exists()
    assert importlib.util.find_spec("aios.integrations.arvo.auth") is not None


@needs_arvo
def test_suite_hmac_cross():
    """AIOS signs with arvo key, ARVO verifies and vice-versa (shared kid)."""
    from aios.integrations.arvo.auth import sign_request as aios_sign, verify_request as aios_verify, _clear_nonces as aios_clear
    import importlib.util

    # load ARVO auth without importing app (avoid env)
    import importlib.machinery

    loader = importlib.machinery.SourceFileLoader("arvo_auth", _arvo_auth_path())
    arvo_auth = loader.load_module()

    aios_clear()
    arvo_auth._clear_nonces()  # type: ignore

    kid, key = "suite-kid", "suite-secret-32-bytes-long-key"
    path_arvo = "/api/v1/integrations/aios/v1/health"
    path_aios = "/api/integrations/arvo/v1/health"

    hdr_aios = aios_sign("GET", path_arvo, None, kid, key)
    assert arvo_auth.verify_request(kid, hdr_aios["X-Service-Timestamp"], hdr_aios["X-Service-Nonce"], "GET", path_arvo, None, hdr_aios["X-Service-Signature"], key)  # type: ignore

    hdr_arvo = arvo_auth.sign_request("GET", path_aios, None, kid, key)  # type: ignore
    assert aios_verify(kid, hdr_arvo["X-Service-Timestamp"], hdr_arvo["X-Service-Nonce"], "GET", path_aios, None, hdr_arvo["X-Service-Signature"], key)

    aios_clear()
    arvo_auth._clear_nonces()  # type: ignore


def test_suite_health_both():
    """AIOS health OK, ARVO health mocked via TestClient (suite)."""
    from aios.main import app as aios_app

    c = TestClient(aios_app)
    # AIOS health without auth -> 404 when disabled, 401 when enabled (route exists)
    # default disabled -> 404
    assert c.get("/api/integrations/arvo/v1/health").status_code == 404

    # with valid HMAC -> 200 (feature-flag enabled in test)
    from aios.config import settings
    from aios.integrations.arvo.auth import sign_request, _clear_nonces
    from aios.integrations.arvo.routes import _clear_events

    orig = (settings.arvo_integration_enabled, settings.arvo_service_key_id, settings.arvo_service_key)
    try:
        settings.arvo_integration_enabled = True
        settings.arvo_service_key_id = "suite-kid"
        settings.arvo_service_key = "suite-secret"
        _clear_nonces()
        _clear_events()
        path = "/api/integrations/arvo/v1/health"
        hdr = sign_request("GET", path, None, "suite-kid", "suite-secret")
        assert c.get(path, headers=hdr).status_code == 200
        # events idempotent suite
        import json as _json

        body = _json.dumps({"type": "deal.created", "payload": {"suite": True}}, separators=(",", ":")).encode()
        hdr2 = sign_request("POST", "/api/integrations/arvo/v1/events", body, "suite-kid", "suite-secret", idempotency_key="suite-1")
        hdr2["Idempotency-Key"] = "suite-1"
        hdr2["Content-Type"] = "application/json"
        r = c.post("/api/integrations/arvo/v1/events", content=body, headers=hdr2)
        assert r.status_code == 200 and r.json()["deduplicated"] is False
        hdr3 = sign_request("POST", "/api/integrations/arvo/v1/events", body, "suite-kid", "suite-secret", idempotency_key="suite-1")
        hdr3["Idempotency-Key"] = "suite-1"
        hdr3["Content-Type"] = "application/json"
        r2 = c.post("/api/integrations/arvo/v1/events", content=body, headers=hdr3)
        assert r2.json()["deduplicated"] is True
    finally:
        settings.arvo_integration_enabled, settings.arvo_service_key_id, settings.arvo_service_key = orig
        _clear_nonces()
        _clear_events()


def test_suite_control_center_exists():
    """Control Center route exists as suite dashboard."""
    from aios.main import app

    c = TestClient(app)
    # unauth -> redirect to login (suite still has dashboard)
    assert c.get("/dashboard/control-center", follow_redirects=False).status_code in (200, 302, 303, 307)


async def test_event_retry_uses_fresh_hmac_nonce(monkeypatch):
    import httpx
    from aios.config import settings
    from aios.integrations.arvo.client import send_event

    nonces = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, path, **kwargs):
            request = httpx.Request(method, f"http://peer.test{path}")
            nonces.append(kwargs["headers"]["X-Service-Nonce"])
            if len(nonces) == 1:
                raise httpx.ConnectError("timeout", request=request)
            return httpx.Response(200, request=request, json={"status": "ok"})

    async def no_sleep(delay):
        return None

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr("aios.integrations.arvo.client.asyncio.sleep", no_sleep)
    monkeypatch.setattr(settings, "arvo_base_url", "http://peer.test")
    monkeypatch.setattr(settings, "arvo_service_key_id", "kid")
    monkeypatch.setattr(settings, "arvo_service_key", "secret")
    await send_event("test.event", {}, "idem")
    assert len(nonces) == 2 and nonces[0] != nonces[1]


async def test_ping_retry_uses_fresh_hmac_nonce(monkeypatch):
    import httpx
    from aios.config import settings
    from aios.integrations.arvo.client import ping

    nonces = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, path, **kwargs):
            nonces.append(kwargs["headers"]["X-Service-Nonce"])
            request = httpx.Request(method, f"http://peer.test{path}")
            status = 503 if len(nonces) < 3 else 200
            return httpx.Response(status, request=request, json={"status": "ok"})

    async def no_sleep(delay):
        return None

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr("aios.integrations.arvo.client.asyncio.sleep", no_sleep)
    monkeypatch.setattr(settings, "arvo_base_url", "http://peer.test")
    monkeypatch.setattr(settings, "arvo_service_key_id", "kid")
    monkeypatch.setattr(settings, "arvo_service_key", "secret")
    await ping()
    assert len(nonces) == 3 and len(set(nonces)) == 3


async def test_commitment_processing_is_org_scoped(test_org, monkeypatch):
    from aios.config import settings
    from sqlalchemy import func, select
    from aios.db.engine import async_session
    from aios.db.models import IntegrationOutbox
    from aios.tasks.jobs import process_commitment_at_risk

    async def no_enqueue(*args, **kwargs):
        return None

    monkeypatch.setattr("aios.tasks.queue.enqueue_job", no_enqueue)
    monkeypatch.setattr(settings, "arvo_integration_enabled", True)
    monkeypatch.setattr(settings, "arvo_base_url", "http://peer.test")
    payload = {"finding_id": "finding-1", "org_id": test_org.id, "business_trace_id": "trace-1"}
    result = await process_commitment_at_risk(None, payload, "trace-1")

    async with async_session() as session:
        assert result["skipped"] is True
        assert await session.scalar(select(func.count(IntegrationOutbox.id))) == 0


async def test_commitment_forwards_amount_to_action_completed(monkeypatch):
    """Exposure and currency from ARVO must reach agent.action.completed verbatim."""
    from types import SimpleNamespace

    from aios.config import settings
    from aios.core.agent import AgentRuntime
    import aios.integrations.arvo.publisher as publisher
    from aios.tasks.jobs import process_commitment_at_risk

    agent = SimpleNamespace(id="agent-amount", governance_config={})

    class FakeResult:
        def scalars(self):
            return self

        def first(self):
            return agent

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, *args, **kwargs):
            return FakeResult()

        def add(self, row):
            pass

        async def commit(self):
            pass

    captured = []

    async def fake_enqueue(event_type, payload, **kwargs):
        captured.append((event_type, payload, kwargs))
        return "outbox-amount"

    async def fake_run(self, conv_id, msg):
        return "action plan"

    def fake_init(self, agent, db_session_factory=None):
        self.agent = agent

    monkeypatch.setattr("aios.db.engine.async_session", lambda: FakeSession())
    monkeypatch.setattr(AgentRuntime, "__init__", fake_init)
    monkeypatch.setattr(AgentRuntime, "run", fake_run)
    monkeypatch.setattr(publisher, "enqueue_outbox", fake_enqueue)
    monkeypatch.setattr(settings, "arvo_integration_enabled", True)
    monkeypatch.setattr(settings, "arvo_base_url", "http://peer.test")

    payload = {
        "org_id": "org-amount",
        "finding_id": "finding-amount",
        "exposure_amount": "1375.50",
        "currency": "BRL",
        "business_trace_id": "trace-amount",
    }
    result = await process_commitment_at_risk(None, payload, "trace-amount")

    assert result["finding_id"] == "finding-amount"
    assert len(captured) == 1
    event_type, event_payload, kwargs = captured[0]
    assert event_type == "agent.action.completed"
    assert event_payload["finding_id"] == "finding-amount"
    assert event_payload["exposure_amount"] == "1375.50"
    assert event_payload["currency"] == "BRL"
    assert "verified_amount" not in event_payload
    assert "recovery_amount" not in event_payload
    assert kwargs["business_trace_id"] == "trace-amount"
    assert kwargs["idempotency_key"] == "agent.action.completed:trace-amount"


async def test_outbox_single_flush_records_failed_attempts(monkeypatch):
    from aios.config import settings
    from aios.db.engine import async_session
    from aios.db.models import IntegrationOutbox
    from aios.integrations.arvo.publisher import enqueue_outbox, integration_outbox_flush

    async def no_enqueue(*args, **kwargs):
        return None

    async def fail_send(*args, **kwargs):
        raise RuntimeError("peer unavailable")

    monkeypatch.setattr("aios.tasks.queue.enqueue_job", no_enqueue)
    monkeypatch.setattr("aios.integrations.arvo.client.send_event", fail_send)
    enabled = settings.arvo_integration_enabled
    base_url = settings.arvo_base_url
    settings.arvo_integration_enabled = True
    settings.arvo_base_url = "http://peer.test"
    try:
        outbox_id = await enqueue_outbox(
            "test.event",
            {"id": "1"},
            idempotency_key="retry-test",
        )
        for _ in range(5):
            with pytest.raises(RuntimeError, match="peer unavailable"):
                await integration_outbox_flush(None, outbox_id)
        async with async_session() as session:
            row = await session.get(IntegrationOutbox, outbox_id)
            assert row.attempts == 5
            assert row.status == "failed"
    finally:
        settings.arvo_integration_enabled = enabled
        settings.arvo_base_url = base_url


async def test_dashboard_sso_arvo_disabled_fails_closed(monkeypatch):
    """Flag off: dashboard SSO fails like ARVO routes, no outbound HTTP."""
    from types import SimpleNamespace

    import httpx
    from fastapi import HTTPException
    from aios.config import settings
    from aios.dashboard.app import sso_arvo

    outbound = []

    class NoHttpClient:
        def __init__(self, *args, **kwargs):
            outbound.append((args, kwargs))
            raise AssertionError("outbound HTTP attempted while ARVO integration disabled")

    monkeypatch.setattr(httpx, "AsyncClient", NoHttpClient)
    monkeypatch.setattr(settings, "arvo_integration_enabled", False)
    request = SimpleNamespace(state=SimpleNamespace(user_id="unused"))

    with pytest.raises(HTTPException) as exc:
        await sso_arvo(request)

    assert exc.value.status_code == 404
    assert exc.value.detail == "ARVO integration disabled"
    assert outbound == []
