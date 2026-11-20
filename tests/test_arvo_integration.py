"""Fase 1 — ARVO integration config + auth self-check. Fase 2 — HMAC + nonce + routes."""
import sys

from aios.integrations.arvo.auth import _clear_nonces, sign_request, verify_request

PATH = "/api/v1/integrations/aios/v1/health"
ROUTE = "/api/integrations/arvo/v1/health"


def test_config_feature_flag_off_default():
    from aios.config import settings
    assert settings.arvo_integration_enabled is False
    assert settings.arvo_service_key_id == ""
    assert settings.arvo_service_key == ""


def test_sign_verify_roundtrip():
    kid, key = "kid-1", "secret-1"
    hdr = sign_request("GET", PATH, None, kid, key)
    assert verify_request(kid, hdr["X-Service-Timestamp"], hdr["X-Service-Nonce"], "GET", PATH, None, hdr["X-Service-Signature"], key)


def test_verify_rejects_wrong_key():
    kid, key = "kid-1", "secret-1"
    hdr = sign_request("GET", PATH, None, kid, key)
    assert not verify_request(kid, hdr["X-Service-Timestamp"], hdr["X-Service-Nonce"], "GET", PATH, None, hdr["X-Service-Signature"], "wrong")


def test_verify_rejects_stale_timestamp():
    kid, key = "kid-1", "secret-1"
    stale = str(int(sys.maxsize // (10**9) * 0.5))
    sig = sign_request("GET", PATH, None, kid, key)["X-Service-Signature"]
    assert not verify_request(kid, stale, "n", "GET", PATH, None, sig, key)


def test_verify_rejects_bad_body_tamper():
    kid, key = "kid-1", "secret-1"
    _clear_nonces()
    hdr = sign_request("POST", PATH, b'{"a":1}', kid, key)
    assert not verify_request(kid, hdr["X-Service-Timestamp"], hdr["X-Service-Nonce"], "POST", PATH, b'{"a":2}', hdr["X-Service-Signature"], key)


def test_verify_rejects_replay():
    kid, key = "kid-1", "secret-1"
    _clear_nonces()
    hdr = sign_request("GET", PATH, None, kid, key)
    assert verify_request(kid, hdr["X-Service-Timestamp"], hdr["X-Service-Nonce"], "GET", PATH, None, hdr["X-Service-Signature"], key)
    assert not verify_request(kid, hdr["X-Service-Timestamp"], hdr["X-Service-Nonce"], "GET", PATH, None, hdr["X-Service-Signature"], key)
    _clear_nonces()


def test_health_requires_auth_when_enabled():
    from fastapi.testclient import TestClient
    from aios.config import settings
    from aios.main import app

    c = TestClient(app)
    orig_enabled, orig_id, orig_key = settings.arvo_integration_enabled, settings.arvo_service_key_id, settings.arvo_service_key
    try:
        settings.arvo_integration_enabled = True
        settings.arvo_service_key_id = "kid-1"
        settings.arvo_service_key = "secret-1"
        _clear_nonces()
        assert c.get(ROUTE).status_code == 401
        hdr = sign_request("GET", ROUTE, None, "kid-1", "secret-1")
        assert c.get(ROUTE, headers=hdr).status_code == 200
        assert c.get(ROUTE, headers=hdr).status_code == 401  # replay
    finally:
        settings.arvo_integration_enabled = orig_enabled
        settings.arvo_service_key_id = orig_id
        settings.arvo_service_key = orig_key
        _clear_nonces()


def test_events_idempotency():
    import json
    from fastapi.testclient import TestClient
    from aios.config import settings
    from aios.integrations.arvo.routes import _clear_events
    from aios.main import app

    c = TestClient(app)
    orig_enabled, orig_id, orig_key = settings.arvo_integration_enabled, settings.arvo_service_key_id, settings.arvo_service_key
    try:
        settings.arvo_integration_enabled = True
        settings.arvo_service_key_id = "kid-1"
        settings.arvo_service_key = "secret-1"
        _clear_nonces()
        _clear_events()
        path = "/api/integrations/arvo/v1/events"
        body = json.dumps({"type": "test.event", "payload": {"a": 1}}, separators=(",", ":")).encode()
        hdr = sign_request("POST", path, body, "kid-1", "secret-1")
        hdr["Idempotency-Key"] = "idem-1"
        hdr["Content-Type"] = "application/json"
        r = c.post(path, content=body, headers=hdr)
        assert r.status_code == 200 and r.json()["deduplicated"] is False
        hdr2 = sign_request("POST", path, body, "kid-1", "secret-1")
        hdr2["Idempotency-Key"] = "idem-1"
        hdr2["Content-Type"] = "application/json"
        r2 = c.post(path, content=body, headers=hdr2)
        assert r2.json()["deduplicated"] is True
    finally:
        settings.arvo_integration_enabled = orig_enabled
        settings.arvo_service_key_id = orig_id
        settings.arvo_service_key = orig_key
        _clear_nonces()
        _clear_events()


async def test_deals_endpoint_auth_and_org_scoping(test_session):
    """ARVO→AIOS CRM read: service-auth + org isolation + data shape."""
    from sqlalchemy import select

    from aios.config import settings
    from aios.db.models import CrmDeal, Organization
    from aios.integrations.arvo.auth import _clear_nonces
    from aios.integrations.arvo.routes import _clear_events
    from aios.main import app
    from httpx import ASGITransport, AsyncClient

    org = Organization(name="Arvo Org", slug="arvo-org", extra_data={})
    test_session.add(org)
    await test_session.flush()
    deal = CrmDeal(
        org_id=org.id, lead_name="Lead X", lead_email="x@x.com",
        stage="prospection", value=1000.0, source="whatsapp",
    )
    test_session.add(deal)
    await test_session.commit()

    orig_enabled, orig_id, orig_key = (
        settings.arvo_integration_enabled, settings.arvo_service_key_id, settings.arvo_service_key,
    )
    try:
        settings.arvo_integration_enabled = True
        settings.arvo_service_key_id = "kid-1"
        settings.arvo_service_key = "secret-1"
        _clear_nonces()
        _clear_events()
        from aios.integrations.arvo.auth import sign_request

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # no auth → 401
            r = await c.get(f"/api/integrations/arvo/v1/deals?org_id={org.id}")
            assert r.status_code == 401

            # auth, correct org → returns the deal
            url = f"/api/integrations/arvo/v1/deals?org_id={org.id}"
            hdr = sign_request("GET", "/api/integrations/arvo/v1/deals", None, "kid-1", "secret-1")
            r = await c.get(url, headers=hdr)
            assert r.status_code == 200
            body = r.json()
            assert body["org_id"] == org.id
            assert body["count"] == 1
            assert body["deals"][0]["lead_name"] == "Lead X"
            assert body["deals"][0]["value"] == 1000.0

            # replay → 401
            r2 = await c.get(url, headers=hdr)
            assert r2.status_code == 401

            # different org → empty (no leak)
            url2 = "/api/integrations/arvo/v1/deals?org_id=other-org"
            hdr2 = sign_request("GET", "/api/integrations/arvo/v1/deals", None, "kid-1", "secret-1")
            r3 = await c.get(url2, headers=hdr2)
            assert r3.status_code == 200
            assert r3.json()["count"] == 0
    finally:
        settings.arvo_integration_enabled = orig_enabled
        settings.arvo_service_key_id = orig_id
        settings.arvo_service_key = orig_key
        _clear_nonces()
        _clear_events()
