"""Suite AIOS+ARVO — HMAC cross, events, suite health."""

import pytest
from fastapi.testclient import TestClient


def test_suite_imports():
    """Both services importable as suite."""
    import aios.main  # noqa: F401
    import importlib.util
    import pathlib

    arvo_main = pathlib.Path("/home/pixor/ai_projects/claude_projects/arvo/app/main.py")
    assert arvo_main.exists()
    assert importlib.util.find_spec("aios.integrations.arvo.auth") is not None


def test_suite_hmac_cross():
    """AIOS signs with arvo key, ARVO verifies and vice-versa (shared kid)."""
    from aios.integrations.arvo.auth import sign_request as aios_sign, verify_request as aios_verify, _clear_nonces as aios_clear
    import importlib.util

    # load ARVO auth without importing app (avoid env)
    import importlib.machinery

    loader = importlib.machinery.SourceFileLoader("arvo_auth", "/home/pixor/ai_projects/claude_projects/arvo/app/integrations/aios/auth.py")
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

        body = _json.dumps({"type": "suite.test", "payload": {"suite": True}}, separators=(",", ":")).encode()
        hdr2 = sign_request("POST", "/api/integrations/arvo/v1/events", body, "suite-kid", "suite-secret")
        hdr2["Idempotency-Key"] = "suite-1"
        hdr2["Content-Type"] = "application/json"
        r = c.post("/api/integrations/arvo/v1/events", content=body, headers=hdr2)
        assert r.status_code == 200 and r.json()["deduplicated"] is False
        hdr3 = sign_request("POST", "/api/integrations/arvo/v1/events", body, "suite-kid", "suite-secret")
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
