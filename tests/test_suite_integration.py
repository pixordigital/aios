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
    from sqlalchemy import select
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
        assert result == {"skipped": True, "reason": "no active agent"}
        rows = (await session.scalars(
            select(IntegrationOutbox).where(
                IntegrationOutbox.business_trace_id == "trace-1",
                IntegrationOutbox.event_type == "agent.action.completed",
            )
        )).all()
        assert len(rows) == 1
        payload = rows[0].payload
        assert payload["status"] == "failed"
        assert payload["reason"] == "no active agent"
        assert payload["finding_id"] == "finding-1"
        assert payload["org_id"] == test_org.id
        for amount_field in ("exposure_amount", "verified_amount", "recovery_amount"):
            assert amount_field not in payload


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


async def test_enqueue_outbox_session_bound_defers_flush_until_commit(monkeypatch):
    """Session-bound enqueue adds/flushes row; no commit or flush job before commit."""
    import asyncio

    import aios.integrations.arvo.publisher as publisher

    class FakeSyncSession:
        pass

    class FakeNested:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *args):
            return None

    class FakeSession:
        def __init__(self):
            self.sync_session = FakeSyncSession()
            self.added = []
            self.flush_count = 0
            self.committed = False
            self.nested_count = 0

        async def scalar(self, stmt):
            return None

        def add(self, row):
            self.added.append(row)
            if not row.id:
                row.id = "outbox-bound"

        async def flush(self):
            self.flush_count += 1

        def begin_nested(self):
            self.nested_count += 1
            return FakeNested()

        async def commit(self):
            self.committed = True

    session = FakeSession()
    listeners = []
    scheduled = []

    def fake_listen(target, identifier, fn, **kw):
        if target is session.sync_session:
            listeners.append((target, identifier, fn, kw))

    async def fake_schedule(outbox_id):
        scheduled.append(outbox_id)

    def no_standalone():
        raise AssertionError("standalone session must not be used")

    monkeypatch.setattr(publisher.event, "listen", fake_listen)
    monkeypatch.setattr(publisher, "schedule_flush", fake_schedule)
    monkeypatch.setattr(publisher, "async_session", no_standalone)

    outbox_id = await publisher.enqueue_outbox(
        "deal.created", {"id": "1"}, idempotency_key="bound-1", session=session
    )

    assert outbox_id == "outbox-bound"
    assert len(session.added) == 1 and session.added[0].status == "pending"
    assert session.flush_count == 1 and not session.committed
    assert session.nested_count == 1
    assert scheduled == []
    assert len(listeners) == 1
    assert listeners[0][1] == "after_commit" and listeners[0][3].get("once") is True
    listeners[0][2](session.sync_session)
    await asyncio.sleep(0)
    assert scheduled == ["outbox-bound"]


async def test_session_bound_enqueue_failure_keeps_domain_transaction(test_org):
    """Failed outbox savepoint rolls back only outbox; domain commit survives."""
    from sqlalchemy import event, select

    from aios.db.engine import async_session
    from aios.db.models import CrmDeal, IntegrationOutbox
    from aios.integrations.arvo.publisher import enqueue_outbox

    key = "savepoint-failure"
    async with async_session() as session:
        deal = CrmDeal(
            org_id=test_org.id,
            lead_name="Savepoint",
            lead_email="",
            lead_phone="",
            value=0,
            stage="prospection",
            pipeline="default",
        )
        session.add(deal)
        await session.flush()
        deal_id = deal.id

        def fail_outbox(sess, flush_context, instances):
            for obj in sess.new:
                if isinstance(obj, IntegrationOutbox) and obj.idempotency_key == key:
                    raise RuntimeError("forced outbox failure")

        event.listen(session.sync_session, "before_flush", fail_outbox)
        try:
            with pytest.raises(RuntimeError, match="forced outbox failure"):
                await enqueue_outbox(
                    "deal.created", {"deal_id": deal_id}, idempotency_key=key, session=session
                )
        finally:
            event.remove(session.sync_session, "before_flush", fail_outbox)

        await session.commit()
        assert await session.get(CrmDeal, deal_id) is not None
        assert await session.scalar(
            select(IntegrationOutbox.id).where(IntegrationOutbox.idempotency_key == key)
        ) is None


class _FakeDashboardRequest:
    async def form(self):
        return {}


async def test_dashboard_crm_create_enqueues_in_domain_session(monkeypatch):
    """Create flushes domain row, enqueues with same session, then commits."""
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    import aios.dashboard.app as dashboard
    import aios.integrations.arvo.publisher as publisher

    order = []
    captured = {}

    class FakeSession:
        async def flush(self):
            order.append("flush")

        async def commit(self):
            order.append("commit")

        async def refresh(self, row):
            return None

    class FakeBackend:
        def __init__(self):
            self._session = FakeSession()
            self.deal = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, model, ident):
            return SimpleNamespace(id="org-1", extra_data={})

        def add(self, row):
            row.id = "deal-1"
            self.deal = row

        async def flush(self):
            await self._session.flush()

        async def commit(self):
            await self._session.commit()

        async def refresh(self, row):
            await self._session.refresh(row)

    db = FakeBackend()

    @asynccontextmanager
    async def fake_db_session():
        yield db

    async def fake_org_filter(request):
        return "org-1"

    async def fake_enqueue(event_type, payload, **kwargs):
        order.append("enqueue")
        captured.update(event_type=event_type, payload=payload, kwargs=kwargs)
        assert kwargs["session"] is db
        return "outbox-1"

    monkeypatch.setattr(dashboard, "db_session", fake_db_session)
    monkeypatch.setattr(dashboard, "_org_filter", fake_org_filter)
    monkeypatch.setattr(publisher, "enqueue_outbox", fake_enqueue)

    response = await dashboard.crm_create(_FakeDashboardRequest(), lead_name="Lead")

    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard/crm"
    assert order == ["flush", "enqueue", "commit"]
    assert captured["event_type"] == "deal.created"
    assert captured["payload"]["deal_id"] == "deal-1"
    assert captured["kwargs"]["idempotency_key"] == "deal.created:deal-1"
    assert captured["kwargs"]["business_trace_id"] == "deal-1"


async def test_dashboard_crm_move_enqueues_in_domain_session(monkeypatch):
    """Move enqueues with same session before commit, keeping existing key."""
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    import aios.dashboard.app as dashboard
    import aios.integrations.arvo.publisher as publisher

    order = []
    captured = {}

    class FakeBackend:
        def __init__(self):
            self._session = SimpleNamespace(flush=None, commit=None)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, model, ident):
            return SimpleNamespace(id="deal-2", org_id="org-1", stage="prospection", value=42.0)

        async def commit(self):
            order.append("commit")

    db = FakeBackend()

    @asynccontextmanager
    async def fake_db_session():
        yield db

    async def fake_org_filter(request):
        return "org-1"

    async def fake_enqueue(event_type, payload, **kwargs):
        order.append("enqueue")
        captured.update(event_type=event_type, payload=payload, kwargs=kwargs)
        assert kwargs["session"] is db
        return "outbox-2"

    monkeypatch.setattr(dashboard, "db_session", fake_db_session)
    monkeypatch.setattr(dashboard, "_org_filter", fake_org_filter)
    monkeypatch.setattr(publisher, "enqueue_outbox", fake_enqueue)

    response = await dashboard.crm_move(
        _FakeDashboardRequest(), "deal-2", "proposal"
    )

    assert response.status_code == 303
    assert order == ["enqueue", "commit"]
    assert captured["event_type"] == "deal.stage_changed"
    assert captured["kwargs"]["idempotency_key"] == "deal.stage:deal-2:proposal"
    assert captured["payload"]["old_stage"] == "prospection"


async def test_dashboard_crm_create_enqueue_failure_aborts_commit(monkeypatch, caplog):
    """Enqueue failure logs warning and aborts deal commit."""
    import logging
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    import aios.dashboard.app as dashboard
    import aios.integrations.arvo.publisher as publisher

    class FakeBackend:
        def __init__(self):
            self._session = SimpleNamespace(flush=None)
            self.committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, model, ident):
            return SimpleNamespace(id="org-1", extra_data={})

        def add(self, row):
            row.id = "deal-3"

        async def flush(self):
            return None

        async def commit(self):
            self.committed = True

        async def refresh(self, row):
            return None

    db = FakeBackend()

    @asynccontextmanager
    async def fake_db_session():
        yield db

    async def fake_org_filter(request):
        return "org-1"

    async def fail_enqueue(*args, **kwargs):
        raise RuntimeError("outbox down")

    monkeypatch.setattr(dashboard, "db_session", fake_db_session)
    monkeypatch.setattr(dashboard, "_org_filter", fake_org_filter)
    monkeypatch.setattr(publisher, "enqueue_outbox", fail_enqueue)

    with caplog.at_level(logging.DEBUG, logger="aios.dashboard.app"):
        with pytest.raises(RuntimeError, match="outbox down"):
            await dashboard.crm_create(_FakeDashboardRequest(), lead_name="Lead")

    assert db.committed is False
    assert any(
        record.levelno == logging.WARNING
        and "event will not be published" in record.message
        and "RuntimeError" in record.message
        for record in caplog.records
    )
    assert not any("outbox down" in record.message for record in caplog.records)
    assert not any(
        "enqueue skipped" in record.message for record in caplog.records
    )


async def test_dashboard_crm_move_enqueue_failure_aborts_commit(monkeypatch, caplog):
    """Move enqueue failure logs warning and aborts stage change commit."""
    import logging
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    import aios.dashboard.app as dashboard
    import aios.integrations.arvo.publisher as publisher

    class FakeBackend:
        def __init__(self):
            self._session = SimpleNamespace(flush=None)
            self.committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, model, ident):
            return SimpleNamespace(id="deal-4", org_id="org-1", stage="prospection", value=42.0)

        async def commit(self):
            self.committed = True

    db = FakeBackend()

    @asynccontextmanager
    async def fake_db_session():
        yield db

    async def fake_org_filter(request):
        return "org-1"

    async def fail_enqueue(*args, **kwargs):
        raise RuntimeError("outbox down")

    monkeypatch.setattr(dashboard, "db_session", fake_db_session)
    monkeypatch.setattr(dashboard, "_org_filter", fake_org_filter)
    monkeypatch.setattr(publisher, "enqueue_outbox", fail_enqueue)

    with caplog.at_level(logging.DEBUG, logger="aios.dashboard.app"):
        with pytest.raises(RuntimeError, match="outbox down"):
            await dashboard.crm_move(_FakeDashboardRequest(), "deal-4", "proposal")

    assert db.committed is False
    assert any(
        record.levelno == logging.WARNING
        and "event will not be published" in record.message
        and "RuntimeError" in record.message
        for record in caplog.records
    )
    assert not any("outbox down" in record.message for record in caplog.records)


async def test_enqueue_outbox_standalone_commits_and_schedules(monkeypatch, caplog):
    """Standalone path commits pending row; scheduling failure warns, keeps row."""
    import logging

    import aios.integrations.arvo.publisher as publisher

    sessions = []

    class FakeSession:
        def __init__(self):
            self.added = []
            self.committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def scalar(self, stmt):
            return None

        def add(self, row):
            row.id = "outbox-standalone"
            self.added.append(row)

        async def commit(self):
            self.committed = True

        async def refresh(self, row):
            return None

    def fake_async_session():
        session = FakeSession()
        sessions.append(session)
        return session

    scheduled = []

    async def ok_enqueue(*args, **kwargs):
        scheduled.append(kwargs["outbox_id"])

    async def fail_enqueue(*args, **kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr(publisher, "async_session", fake_async_session)
    monkeypatch.setattr("aios.tasks.queue.enqueue_job", ok_enqueue)

    outbox_id = await publisher.enqueue_outbox(
        "test.event", {}, idempotency_key="standalone-ok"
    )
    assert outbox_id == "outbox-standalone"
    assert sessions[0].committed is True
    assert sessions[0].added[0].status == "pending"
    assert scheduled == ["outbox-standalone"]

    monkeypatch.setattr("aios.tasks.queue.enqueue_job", fail_enqueue)
    with caplog.at_level(logging.WARNING, logger="aios.integrations.arvo.publisher"):
        outbox_id = await publisher.enqueue_outbox(
            "test.event", {}, idempotency_key="standalone-fail"
        )

    assert outbox_id == "outbox-standalone"
    assert sessions[1].committed is True
    assert sessions[1].added[0].status == "pending"
    assert any(
        record.levelno == logging.WARNING
        and "row remains pending" in record.message
        for record in caplog.records
    )


@pytest.mark.parametrize(
    "status_code,expected_status",
    [(422, "pending"), (400, "failed"), (403, "failed"), (404, "failed"), (None, "pending")],
)
async def test_deliver_retryability(monkeypatch, status_code, expected_status):
    """422 is retryable like transport errors; other 4xx stay terminal."""
    import httpx
    from types import SimpleNamespace

    import aios.integrations.arvo.publisher as publisher

    row = SimpleNamespace(
        id="outbox-deliver",
        event_type="test.event",
        payload={},
        idempotency_key="deliver-1",
        business_trace_id="trace-deliver",
        attempts=1,
        status="processing",
        last_error=None,
        sent_at=None,
    )

    def make_error():
        request = httpx.Request("POST", "http://peer.test")
        if status_code is None:
            return httpx.ConnectError("peer down", request=request)
        response = httpx.Response(status_code, request=request)
        return httpx.HTTPStatusError(
            f"status {status_code}", request=request, response=response
        )

    calls = []

    async def fail_send(*args, **kwargs):
        calls.append(kwargs["idempotency_key"])
        raise make_error()

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, model, ident):
            return row

        async def commit(self):
            return None

    async def fake_notify(*args):
        return None

    monkeypatch.setattr("aios.integrations.arvo.client.send_event", fail_send)
    monkeypatch.setattr(publisher, "async_session", lambda: FakeSession())
    monkeypatch.setattr(publisher, "_notify_exhausted", fake_notify)

    result = await publisher._deliver(row, raise_errors=False)

    assert result is False
    assert row.status == expected_status
    assert row.last_error is not None
    assert calls == ["deliver-1"]

    if status_code == 422:
        row.attempts += 1
        row.status = "processing"
        result = await publisher._deliver(row, raise_errors=False)
        assert result is False
        assert row.status == "pending"
        assert calls == ["deliver-1", "deliver-1"]
