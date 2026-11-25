"""Fase 1 — ARVO integration config + auth self-check. Fase 2 — HMAC + nonce + routes."""
import sys

import pytest

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
        body = json.dumps({"type": "action.executed", "payload": {"a": 1}}, separators=(",", ":")).encode()
        hdr = sign_request("POST", path, body, "kid-1", "secret-1", idempotency_key="idem-1")
        hdr["Idempotency-Key"] = "idem-1"
        hdr["Content-Type"] = "application/json"
        r = c.post(path, content=body, headers=hdr)
        assert r.status_code == 200 and r.json()["deduplicated"] is False
        hdr2 = sign_request("POST", path, body, "kid-1", "secret-1", idempotency_key="idem-1")
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


def test_events_reject_unknown_type_before_idempotency():
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
        key = "idem-unknown-type"

        unknown = json.dumps({"type": "not.a.real.event", "payload": {"a": 1}}, separators=(",", ":")).encode()
        hdr = sign_request("POST", path, unknown, "kid-1", "secret-1", idempotency_key=key)
        hdr["Idempotency-Key"] = key
        hdr["Content-Type"] = "application/json"
        assert c.post(path, content=unknown, headers=hdr).status_code == 400

        # Rejected type must not claim the key: valid event still processes.
        known = json.dumps({"type": "action.executed", "payload": {"action_id": "a-1"}}, separators=(",", ":")).encode()
        hdr2 = sign_request("POST", path, known, "kid-1", "secret-1", idempotency_key=key)
        hdr2["Idempotency-Key"] = key
        hdr2["Content-Type"] = "application/json"
        r2 = c.post(path, content=known, headers=hdr2)
        assert r2.status_code == 200
        assert r2.json()["deduplicated"] is False
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
            hdr = sign_request("GET", "/api/integrations/arvo/v1/deals", None, "kid-1", "secret-1", query=f"org_id={org.id}")
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
            hdr2 = sign_request("GET", "/api/integrations/arvo/v1/deals", None, "kid-1", "secret-1", query="org_id=other-org")
            r3 = await c.get(url2, headers=hdr2)
            assert r3.status_code == 200
            assert r3.json()["count"] == 0
    finally:
        settings.arvo_integration_enabled = orig_enabled
        settings.arvo_service_key_id = orig_id
        settings.arvo_service_key = orig_key
        _clear_nonces()
        _clear_events()


async def test_action_executed_event_audits(test_session):
    from sqlalchemy import select

    from aios.config import settings
    from aios.db.models import AuditLog, Organization
    from aios.integrations.arvo.auth import _clear_nonces
    from aios.integrations.arvo.routes import _clear_events
    from aios.main import app
    from httpx import ASGITransport, AsyncClient

    org = Organization(name="Exec Org", slug="exec-org", extra_data={})
    test_session.add(org)
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
            path = "/api/integrations/arvo/v1/events"
            body = {"type": "action.executed", "payload": {"org_id": org.id, "action_id": "act-1", "finding_id": "f-1"}}
            import json
            raw = json.dumps(body, separators=(",", ":")).encode()
            hdr = sign_request("POST", path, raw, "kid-1", "secret-1", idempotency_key="idem-exec-1")
            hdr["Idempotency-Key"] = "idem-exec-1"
            hdr["Content-Type"] = "application/json"
            r = await c.post(path, content=raw, headers=hdr)
            assert r.status_code == 200
            assert r.json()["handled"] == "action.executed"

        # audit row created
        rows = (await test_session.execute(
            select(AuditLog).where(AuditLog.org_id == org.id, AuditLog.action == "action.executed")
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].resource_id == "act-1"
    finally:
        settings.arvo_integration_enabled = orig_enabled
        settings.arvo_service_key_id = orig_id
        settings.arvo_service_key = orig_key
        _clear_nonces()
        _clear_events()


async def test_action_verified_updates_deal(test_session):
    from sqlalchemy import select

    from aios.config import settings
    from aios.db.models import CrmDeal, Organization
    from aios.integrations.arvo.auth import _clear_nonces
    from aios.integrations.arvo.routes import _clear_events
    from aios.main import app
    from httpx import ASGITransport, AsyncClient

    org = Organization(name="Ver Org", slug="ver-org", extra_data={})
    test_session.add(org)
    await test_session.flush()
    deal = CrmDeal(org_id=org.id, lead_name="Ver Deal", stage="prospection", value=500.0)
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
        import json

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            path = "/api/integrations/arvo/v1/events"
            body = {"type": "action.verified", "payload": {
                "org_id": org.id, "action_id": "act-v", "finding_id": "f-v",
                "verified_amount": "300.00", "deal_id": deal.id,
            }}
            raw = json.dumps(body, separators=(",", ":")).encode()
            hdr = sign_request("POST", path, raw, "kid-1", "secret-1", idempotency_key="idem-ver-1")
            hdr["Idempotency-Key"] = "idem-ver-1"
            hdr["Content-Type"] = "application/json"
            r = await c.post(path, content=raw, headers=hdr)
            assert r.status_code == 200
            assert r.json()["handled"] == "action.verified"
            assert r.json()["deal_updated"] is True

        # deal updated
        await test_session.refresh(deal)
        assert deal.stage == "closed_won"
        assert deal.extra_data.get("recovered_brl") == "300.00"
    finally:
        settings.arvo_integration_enabled = orig_enabled
        settings.arvo_service_key_id = orig_id
        settings.arvo_service_key = orig_key
        _clear_nonces()
        _clear_events()


def test_events_accept_envelope_without_version():
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
        body = json.dumps({"type": "action.executed", "payload": {"action_id": "a-nov", "business_trace_id": "trace-nov"}}, separators=(",", ":")).encode()
        hdr = sign_request("POST", path, body, "kid-1", "secret-1", idempotency_key="idem-nov-version")
        hdr["Idempotency-Key"] = "idem-nov-version"
        hdr["Content-Type"] = "application/json"
        r = c.post(path, content=body, headers=hdr)
        assert r.status_code == 200
        assert r.json()["event_version"] == "1"
        assert r.json()["business_trace_id"] == "trace-nov"
    finally:
        settings.arvo_integration_enabled = orig_enabled
        settings.arvo_service_key_id = orig_id
        settings.arvo_service_key = orig_key
        _clear_nonces()
        _clear_events()


async def test_agent_run_persists_business_trace_in_audit(test_session, test_org, monkeypatch):
    from sqlalchemy import select

    from aios.config import settings
    from aios.core.agent import AgentRuntime
    from aios.db.models import Agent, AuditLog
    from aios.tasks.jobs import process_commitment_at_risk

    agent = Agent(name="Trace Agent", org_id=test_org.id, status="active")
    test_session.add(agent)
    await test_session.commit()
    await test_session.refresh(agent)

    async def fake_run(self, conv_id, msg):
        return "action plan"

    async def no_enqueue(*args, **kwargs):
        return None

    monkeypatch.setattr(AgentRuntime, "run", fake_run)
    monkeypatch.setattr("aios.integrations.arvo.publisher.enqueue_outbox", no_enqueue)
    monkeypatch.setattr(settings, "arvo_integration_enabled", True)
    monkeypatch.setattr(settings, "arvo_base_url", "http://peer.test")

    result = await process_commitment_at_risk(
        None, {"org_id": test_org.id, "finding_id": "f-trace"}, "trace-agent-1"
    )
    assert result["business_trace_id"] == "trace-agent-1"

    row = (await test_session.execute(
        select(AuditLog).where(AuditLog.org_id == test_org.id, AuditLog.action == "agent.execution")
    )).scalar_one()
    assert row.resource_id == agent.id
    assert row.details["business_trace_id"] == "trace-agent-1"
    assert row.details["finding_id"] == "f-trace"


async def test_action_verified_db_failure_does_not_cache_event(test_session, monkeypatch):
    """Audit commit failure must surface as error and release idempotency."""
    import json
    from contextlib import asynccontextmanager

    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from aios.config import settings
    from aios.db import engine as db_engine
    from aios.db.models import AuditLog, IntegrationEvent, Organization
    from aios.integrations.arvo.auth import _clear_nonces, sign_request
    from aios.integrations.arvo.routes import _clear_events, _get_idempotent
    from aios.main import app

    org = Organization(name="Fail Org", slug="fail-org", extra_data={})
    test_session.add(org)
    await test_session.commit()

    real_session = db_engine.async_session

    class FailingCommitSession:
        def __init__(self, session):
            self._session = session

        def __getattr__(self, name):
            return getattr(self._session, name)

        async def commit(self):
            if any(isinstance(obj, AuditLog) for obj in self._session.new):
                raise RuntimeError("audit DB down")
            await self._session.commit()

    @asynccontextmanager
    async def failing_async_session():
        async with real_session() as s:
            yield FailingCommitSession(s)

    orig_enabled, orig_id, orig_key = (
        settings.arvo_integration_enabled, settings.arvo_service_key_id, settings.arvo_service_key,
    )
    try:
        settings.arvo_integration_enabled = True
        settings.arvo_service_key_id = "kid-1"
        settings.arvo_service_key = "secret-1"
        _clear_nonces()
        _clear_events()
        path = "/api/integrations/arvo/v1/events"
        raw = json.dumps({"type": "action.verified", "payload": {
            "org_id": org.id, "action_id": "act-fail", "verified_amount": "10.00",
        }}, separators=(",", ":")).encode()
        key = "idem-ver-db-fail"
        c = TestClient(app, raise_server_exceptions=False)

        with monkeypatch.context() as m:
            m.setattr(db_engine, "async_session", failing_async_session)
            hdr = sign_request("POST", path, raw, "kid-1", "secret-1", idempotency_key=key)
            hdr["Idempotency-Key"] = key
            hdr["Content-Type"] = "application/json"
            r = c.post(path, content=raw, headers=hdr)
        assert r.status_code >= 500
        assert _get_idempotent(key) is None
        assert (await test_session.execute(
            select(IntegrationEvent).where(IntegrationEvent.idempotency_key == key)
        )).scalar_one_or_none() is None
        assert (await test_session.execute(
            select(AuditLog).where(AuditLog.org_id == org.id, AuditLog.action == "action.verified")
        )).scalars().all() == []

        # Released key must be reusable; retry processes once.
        hdr2 = sign_request("POST", path, raw, "kid-1", "secret-1", idempotency_key=key)
        hdr2["Idempotency-Key"] = key
        hdr2["Content-Type"] = "application/json"
        r2 = c.post(path, content=raw, headers=hdr2)
        assert r2.status_code == 200 and r2.json()["deduplicated"] is False
        assert len((await test_session.execute(
            select(AuditLog).where(AuditLog.org_id == org.id, AuditLog.action == "action.verified")
        )).scalars().all()) == 1
    finally:
        settings.arvo_integration_enabled = orig_enabled
        settings.arvo_service_key_id = orig_id
        settings.arvo_service_key = orig_key
        _clear_nonces()
        _clear_events()


async def test_commitment_enqueue_failure_leaves_no_audit(test_session, monkeypatch):
    """Queue failure must not commit the audit row; ingest releases the key with 503."""
    import json

    from sqlalchemy import select

    from aios.config import settings
    from aios.db.models import AuditLog, Organization
    from aios.integrations.arvo.auth import _clear_nonces, sign_request
    from aios.integrations.arvo.routes import _clear_events
    from aios.main import app
    from httpx import ASGITransport, AsyncClient

    org = Organization(name="Queue Org", slug="queue-org", extra_data={})
    test_session.add(org)
    await test_session.commit()

    async def fail_enqueue(*args, **kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr("aios.tasks.queue.enqueue_job", fail_enqueue)

    orig_enabled, orig_id, orig_key = (
        settings.arvo_integration_enabled, settings.arvo_service_key_id, settings.arvo_service_key,
    )
    try:
        settings.arvo_integration_enabled = True
        settings.arvo_service_key_id = "kid-1"
        settings.arvo_service_key = "secret-1"
        _clear_nonces()
        _clear_events()
        path = "/api/integrations/arvo/v1/events"
        raw = json.dumps({"type": "commitment.at_risk", "payload": {
            "org_id": org.id, "finding_id": "f-queue-fail",
        }}, separators=(",", ":")).encode()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            hdr = sign_request("POST", path, raw, "kid-1", "secret-1", idempotency_key="idem-commit-queue-fail")
            hdr["Idempotency-Key"] = "idem-commit-queue-fail"
            hdr["Content-Type"] = "application/json"
            r = await c.post(path, content=raw, headers=hdr)
        assert r.status_code == 503
        rows = (await test_session.execute(
            select(AuditLog).where(AuditLog.org_id == org.id, AuditLog.action == "commitment.at_risk")
        )).scalars().all()
        assert rows == []
    finally:
        settings.arvo_integration_enabled = orig_enabled
        settings.arvo_service_key_id = orig_id
        settings.arvo_service_key = orig_key
        _clear_nonces()
        _clear_events()


async def test_commitment_audit_failure_after_enqueue_keeps_reservation(test_session, monkeypatch):
    """Enqueue already happened: audit failure stays 5xx but must keep the key claimed."""
    import json
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from aios.config import settings
    from aios.db import engine as db_engine
    from aios.db.models import AuditLog, IntegrationEvent, Organization
    from aios.integrations.arvo.auth import _clear_nonces, sign_request
    from aios.integrations.arvo.routes import _clear_events, _get_idempotent
    from aios.main import app

    org = Organization(name="Audit Fail Org", slug="audit-fail-org", extra_data={})
    test_session.add(org)
    await test_session.commit()

    real_session = db_engine.async_session

    class FailingCommitSession:
        def __init__(self, session):
            self._session = session

        def __getattr__(self, name):
            return getattr(self._session, name)

        async def commit(self):
            if any(isinstance(obj, AuditLog) for obj in self._session.new):
                raise RuntimeError("audit DB down")
            await self._session.commit()

    @asynccontextmanager
    async def failing_async_session():
        async with real_session() as s:
            yield FailingCommitSession(s)

    fake_enqueue = AsyncMock()
    orig_enabled, orig_id, orig_key = (
        settings.arvo_integration_enabled, settings.arvo_service_key_id, settings.arvo_service_key,
    )
    try:
        settings.arvo_integration_enabled = True
        settings.arvo_service_key_id = "kid-1"
        settings.arvo_service_key = "secret-1"
        _clear_nonces()
        _clear_events()
        path = "/api/integrations/arvo/v1/events"
        raw = json.dumps({"type": "commitment.at_risk", "payload": {
            "org_id": org.id, "finding_id": "f-audit-fail",
        }}, separators=(",", ":")).encode()
        key = "idem-commit-audit-fail"
        c = TestClient(app, raise_server_exceptions=False)

        with monkeypatch.context() as m:
            m.setattr("aios.tasks.queue.enqueue_job", fake_enqueue)
            m.setattr(db_engine, "async_session", failing_async_session)
            hdr = sign_request("POST", path, raw, "kid-1", "secret-1", idempotency_key=key)
            hdr["Idempotency-Key"] = key
            hdr["Content-Type"] = "application/json"
            r = c.post(path, content=raw, headers=hdr)
        assert r.status_code >= 500
        assert fake_enqueue.await_count == 1
        assert _get_idempotent(key) is None
        row = (await test_session.execute(
            select(IntegrationEvent).where(IntegrationEvent.idempotency_key == key)
        )).scalar_one_or_none()
        assert row is not None and row.response.get("status") == "processing"

        # Retry sees the still-claimed key; enqueue must not happen twice.
        hdr2 = sign_request("POST", path, raw, "kid-1", "secret-1", idempotency_key=key)
        hdr2["Idempotency-Key"] = key
        hdr2["Content-Type"] = "application/json"
        r2 = c.post(path, content=raw, headers=hdr2)
        assert r2.status_code == 503
        assert fake_enqueue.await_count == 1
        assert (await test_session.execute(
            select(AuditLog).where(AuditLog.org_id == org.id, AuditLog.action == "commitment.at_risk")
        )).scalars().all() == []
    finally:
        settings.arvo_integration_enabled = orig_enabled
        settings.arvo_service_key_id = orig_id
        settings.arvo_service_key = orig_key
        _clear_nonces()
        _clear_events()


async def test_arvo_allowlist_deals(test_session, monkeypatch):
    """AIOS_ARVO_ALLOWED_ORGS admits listed org; /deals 403s the rest."""
    from aios.config import settings
    from aios.db.models import Organization
    from aios.integrations.arvo.auth import _clear_nonces, sign_request
    from aios.integrations.arvo.routes import _clear_events
    from aios.main import app
    from httpx import ASGITransport, AsyncClient

    org = Organization(name="Allow Org", slug="allow-org", extra_data={})
    test_session.add(org)
    await test_session.commit()

    monkeypatch.setattr(settings, "arvo_integration_enabled", True)
    monkeypatch.setattr(settings, "arvo_service_key_id", "kid-1")
    monkeypatch.setattr(settings, "arvo_service_key", "secret-1")
    monkeypatch.setattr(settings, "arvo_allowed_orgs", f" , {org.id}, ")
    _clear_nonces()
    _clear_events()
    try:
        path = "/api/integrations/arvo/v1/deals"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            hdr = sign_request("GET", path, None, "kid-1", "secret-1", query=f"org_id={org.id}")
            r = await c.get(f"{path}?org_id={org.id}", headers=hdr)
            assert r.status_code == 200
            assert r.json()["org_id"] == org.id

            hdr2 = sign_request("GET", path, None, "kid-1", "secret-1", query="org_id=blocked-org")
            r2 = await c.get(f"{path}?org_id=blocked-org", headers=hdr2)
            assert r2.status_code == 403

            from sqlalchemy import select

            from aios.governance.security import SecurityEvent

            events = (await test_session.execute(
                select(SecurityEvent).where(
                    SecurityEvent.event_type == "security.auth.failure",
                    SecurityEvent.org_id == "blocked-org",
                )
            )).scalars().all()
            assert len(events) == 1
            assert events[0].source == "arvo"
            assert events[0].payload == {"reason": "org_not_allowed", "metric": "auth_failure"}
    finally:
        _clear_nonces()
        _clear_events()


async def test_arvo_allowlist_events(test_session, monkeypatch):
    """Same allowlist gate on /events payload org_id (action.executed)."""
    import json

    from aios.config import settings
    from aios.db.models import Organization
    from aios.integrations.arvo.auth import _clear_nonces, sign_request
    from aios.integrations.arvo.routes import _clear_events
    from aios.main import app
    from httpx import ASGITransport, AsyncClient

    org = Organization(name="Allow Event Org", slug="allow-event-org", extra_data={})
    test_session.add(org)
    await test_session.commit()

    monkeypatch.setattr(settings, "arvo_integration_enabled", True)
    monkeypatch.setattr(settings, "arvo_service_key_id", "kid-1")
    monkeypatch.setattr(settings, "arvo_service_key", "secret-1")
    monkeypatch.setattr(settings, "arvo_allowed_orgs", org.id)
    _clear_nonces()
    _clear_events()
    try:
        path = "/api/integrations/arvo/v1/events"

        async def post_event(org_id: str, key: str):
            raw = json.dumps(
                {"type": "action.executed", "payload": {"org_id": org_id, "action_id": key}},
                separators=(",", ":"),
            ).encode()
            hdr = sign_request("POST", path, raw, "kid-1", "secret-1", idempotency_key=key)
            hdr["Idempotency-Key"] = key
            hdr["Content-Type"] = "application/json"
            return await c.post(path, content=raw, headers=hdr)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await post_event(org.id, "idem-allow-org")
            assert r.status_code == 200
            assert r.json()["handled"] == "action.executed"

            r2 = await post_event("blocked-org", "idem-blocked-org")
            assert r2.status_code == 403

            from sqlalchemy import select

            from aios.governance.security import SecurityEvent

            events = (await test_session.execute(
                select(SecurityEvent).where(
                    SecurityEvent.event_type == "security.auth.failure",
                    SecurityEvent.org_id == "blocked-org",
                )
            )).scalars().all()
            assert len(events) == 1
            assert events[0].source == "arvo"
            assert events[0].payload == {"reason": "org_not_allowed", "metric": "auth_failure"}
    finally:
        _clear_nonces()
        _clear_events()


def test_signature_covers_query_and_idempotency_key():
    """Canonical includes normalized query and idem key; swaps invalidate HMAC."""
    from aios.integrations.arvo.auth import _normalize_query

    kid, key = "kid-q", "secret-q"
    assert _normalize_query("") == ""
    assert _normalize_query("b=2&a=1&empty=") == "a=1&b=2&empty="
    _clear_nonces()
    query = "b=2&a=1&empty="
    hdr = sign_request("GET", PATH, None, kid, key, query=query, idempotency_key="idem-q")
    common = (kid, hdr["X-Service-Timestamp"], hdr["X-Service-Nonce"], "GET", PATH, None, hdr["X-Service-Signature"], key)
    assert not verify_request(*common, query="b=3&a=1&empty=", idempotency_key="idem-q")
    assert not verify_request(*common, query=query, idempotency_key="idem-other")
    assert verify_request(*common, query=query, idempotency_key="idem-q")

    _clear_nonces()
    normalized = sign_request("GET", PATH, None, kid, key, query="a=1&b=2&empty=", idempotency_key="idem-q")
    assert verify_request(
        kid, normalized["X-Service-Timestamp"], normalized["X-Service-Nonce"], "GET", PATH, None,
        normalized["X-Service-Signature"], key, query=query, idempotency_key="idem-q",
    )
    _clear_nonces()


async def test_hmac_rejects_query_and_idempotency_key_tampering(monkeypatch):
    """Endpoint verification binds query string and Idempotency-Key."""
    import json

    from aios.config import settings
    from aios.integrations.arvo.routes import _clear_events
    from aios.main import app
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setattr(settings, "arvo_integration_enabled", True)
    monkeypatch.setattr(settings, "arvo_service_key_id", "kid-tamper")
    monkeypatch.setattr(settings, "arvo_service_key", "secret-tamper")
    _clear_nonces()
    _clear_events()
    try:
        deals = "/api/integrations/arvo/v1/deals"
        events = "/api/integrations/arvo/v1/events"
        raw = json.dumps({"type": "action.executed", "payload": {"action_id": "a-tamper"}}, separators=(",", ":")).encode()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            good = sign_request("GET", deals, None, "kid-tamper", "secret-tamper", query="org_id=org-a&limit=5")
            assert (await c.get(f"{deals}?org_id=org-a&limit=5", headers=good)).status_code == 200

            swapped = sign_request("GET", deals, None, "kid-tamper", "secret-tamper", query="org_id=org-a&limit=5")
            assert (await c.get(f"{deals}?org_id=org-b&limit=5", headers=swapped)).status_code == 401

            bad_key = sign_request("POST", events, raw, "kid-tamper", "secret-tamper", idempotency_key="idem-good")
            bad_key["Idempotency-Key"] = "idem-swapped"
            bad_key["Content-Type"] = "application/json"
            assert (await c.post(events, content=raw, headers=bad_key)).status_code == 401

            good_key = sign_request("POST", events, raw, "kid-tamper", "secret-tamper", idempotency_key="idem-good")
            good_key["Idempotency-Key"] = "idem-good"
            good_key["Content-Type"] = "application/json"
            assert (await c.post(events, content=raw, headers=good_key)).status_code == 200
    finally:
        _clear_nonces()
        _clear_events()


def test_hmac_key_rotation_map_accepts_secondary_and_primary(monkeypatch):
    """Map secures rotation: secondary kid, rotated primary secret and legacy primary all verify."""
    from fastapi.testclient import TestClient

    from aios.config import settings
    from aios.main import app

    monkeypatch.setattr(settings, "arvo_integration_enabled", True)
    monkeypatch.setattr(settings, "arvo_service_key_id", "kid-primary")
    monkeypatch.setattr(settings, "arvo_service_key", "secret-primary")
    monkeypatch.setattr(settings, "arvo_service_keys", "kid-secondary:secret-secondary, kid-primary:secret-rotated")
    _clear_nonces()
    c = TestClient(app)
    try:
        def call(kid: str, secret: str) -> int:
            return c.get(ROUTE, headers=sign_request("GET", ROUTE, None, kid, secret)).status_code

        assert call("kid-secondary", "secret-secondary") == 200
        assert call("kid-primary", "secret-rotated") == 200
        assert call("kid-primary", "secret-primary") == 200
        assert call("kid-primary", "secret-wrong") == 401
    finally:
        _clear_nonces()


def test_hmac_key_map_strips_entries_and_skips_malformed():
    """CSV tolerates outer spaces; blank/malformed stay skipped; primary fallback kept."""
    from aios.integrations.arvo.auth import verification_keys

    primary_kid, primary_key = "kid-primary", "secret-primary"
    malformed = " kid-bad , :secret-no-kid, kid-no-secret:, kid-blank:   "
    assert verification_keys(primary_kid, primary_key, " kid-spaced : secret-spaced ", "kid-spaced") == ["secret-spaced"]
    assert verification_keys(primary_kid, primary_key, malformed, "kid-bad") == []
    assert verification_keys(primary_kid, primary_key, malformed, "kid-primary") == [primary_key]
    assert verification_keys(primary_kid, primary_key, " kid-primary : secret-rotated ", "kid-primary") == ["secret-rotated", primary_key]


def test_hmac_key_map_spaced_entry_verifies_and_tamper_rejected():
    from aios.integrations.arvo.auth import _clear_nonces, verification_keys, verify_request

    _clear_nonces()
    try:
        hdr = sign_request("GET", PATH, None, "kid-spaced", "secret-spaced")
        keys = verification_keys("kid-primary", "secret-primary", " kid-spaced : secret-spaced ", "kid-spaced")
        assert keys == ["secret-spaced"]
        common = (
            "kid-spaced", hdr["X-Service-Timestamp"], hdr["X-Service-Nonce"],
            "GET", PATH, None, hdr["X-Service-Signature"],
        )
        assert not verify_request(*common, keys[0], query="tampered=1")
        assert verify_request(*common, keys[0])
    finally:
        _clear_nonces()


@pytest.mark.parametrize("with_org", [True, False])
async def test_completion_failure_marker_survives_past_60s(test_session, monkeypatch, with_org):
    """Side effect commits its own done marker; completion-write failure still dedups past 60s."""
    import json
    from datetime import datetime as real_datetime, timedelta, timezone

    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from aios.config import settings
    from aios.db.models import AuditLog, IntegrationEvent, Organization
    from aios.integrations.arvo import routes
    from aios.integrations.arvo.auth import _clear_nonces, sign_request
    from aios.main import app

    org = None
    if with_org:
        org = Organization(name="Replay Org", slug="replay-org", extra_data={})
        test_session.add(org)
        await test_session.commit()
    org_id = org.id if org else None

    key = f"idem-complete-fail-replay-{int(with_org)}"
    handler_calls: list[str] = []
    clock = [0]

    class ShiftedDatetime:
        @classmethod
        def now(cls, tz=None):
            return real_datetime.now(tz) + timedelta(seconds=clock[0])

    real_handler = routes._handle_action_executed

    async def counted_handler(payload, trace_id, idempotency_key, response=None):
        handler_calls.append(idempotency_key)
        return await real_handler(payload, trace_id, idempotency_key, response)

    async def fail_complete(event_key, response):
        raise RuntimeError("completion write down")

    monkeypatch.setattr(routes, "_handle_action_executed", counted_handler)
    monkeypatch.setattr(routes, "_db_complete_event", fail_complete)
    monkeypatch.setattr(settings, "arvo_integration_enabled", True)
    monkeypatch.setattr(settings, "arvo_service_key_id", "kid-1")
    monkeypatch.setattr(settings, "arvo_service_key", "secret-1")
    _clear_nonces()
    routes._clear_events()

    path = "/api/integrations/arvo/v1/events"
    payload = {"action_id": "act-replay"}
    if org_id:
        payload["org_id"] = org_id
    raw = json.dumps({"type": "action.executed", "payload": payload}, separators=(",", ":")).encode()
    c = TestClient(app, raise_server_exceptions=False)
    try:
        hdr = sign_request("POST", path, raw, "kid-1", "secret-1", idempotency_key=key)
        hdr["Idempotency-Key"] = key
        hdr["Content-Type"] = "application/json"
        first = c.post(path, content=raw, headers=hdr)
        assert first.status_code >= 500
        assert handler_calls == [key]

        row = (await test_session.execute(
            select(IntegrationEvent).where(IntegrationEvent.idempotency_key == key)
        )).scalar_one()
        if with_org:
            assert row.response["status"] == "processed"
            assert row.response["handled"] == "action.executed"
            assert row.expires_at > real_datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=60)
        else:
            assert row.response["status"] == "processing"

        # No sleeps: move the route clock past the old 60s claim window.
        clock[0] = 61
        monkeypatch.setattr(routes, "datetime", ShiftedDatetime)
        if with_org:
            # In-memory cache would mask DB authority; clear it to force DB dedup.
            routes._clear_events()
        hdr2 = sign_request("POST", path, raw, "kid-1", "secret-1", idempotency_key=key)
        hdr2["Idempotency-Key"] = key
        hdr2["Content-Type"] = "application/json"
        retry = c.post(path, content=raw, headers=hdr2)
        assert retry.status_code == 200 and retry.json()["deduplicated"] is True
        assert retry.json()["handled"] == "action.executed"
        assert handler_calls == [key]

        await test_session.rollback()
        if with_org:
            audits = (await test_session.execute(
                select(AuditLog).where(AuditLog.org_id == org_id, AuditLog.action == "action.executed")
            )).scalars().all()
            assert len(audits) == 1
    finally:
        _clear_nonces()
        routes._clear_events()


async def test_commitment_no_org_completion_failure_caches_full_response(test_session, monkeypatch):
    """No-org success must update resp_base before completion write, so failure cache keeps handled/enqueued."""
    import json
    from unittest.mock import AsyncMock

    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from aios.config import settings
    from aios.db.models import IntegrationEvent
    from aios.integrations.arvo import routes
    from aios.integrations.arvo.auth import _clear_nonces, sign_request
    from aios.main import app

    key = "idem-commit-no-org-complete-fail"
    finding_id = "f-no-org-complete-fail"
    fake_enqueue = AsyncMock()

    async def fail_complete(event_key, response):
        raise RuntimeError("completion write down")

    monkeypatch.setattr("aios.tasks.queue.enqueue_job", fake_enqueue)
    monkeypatch.setattr(routes, "_db_complete_event", fail_complete)
    monkeypatch.setattr(settings, "arvo_integration_enabled", True)
    monkeypatch.setattr(settings, "arvo_service_key_id", "kid-1")
    monkeypatch.setattr(settings, "arvo_service_key", "secret-1")
    _clear_nonces()
    routes._clear_events()

    path = "/api/integrations/arvo/v1/events"
    raw = json.dumps({"type": "commitment.at_risk", "payload": {"finding_id": finding_id}}, separators=(",", ":")).encode()
    c = TestClient(app, raise_server_exceptions=False)
    try:
        hdr = sign_request("POST", path, raw, "kid-1", "secret-1", idempotency_key=key)
        hdr["Idempotency-Key"] = key
        hdr["Content-Type"] = "application/json"
        r = c.post(path, content=raw, headers=hdr)
        assert r.status_code >= 500
        assert fake_enqueue.await_count == 1

        cached = routes._get_idempotent(key)
        assert cached == {
            "status": "processed",
            "idempotency_key": key,
            "type": "commitment.at_risk",
            "business_trace_id": finding_id,
            "event_version": "1",
            "handled": "commitment.at_risk",
            "finding_id": finding_id,
            "enqueued": True,
        }

        row = (await test_session.execute(
            select(IntegrationEvent).where(IntegrationEvent.idempotency_key == key)
        )).scalar_one()
        assert row.response == {"status": "processing"}
    finally:
        _clear_nonces()
        routes._clear_events()
