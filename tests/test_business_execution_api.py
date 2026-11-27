from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from aios.api.business_execution import router
from aios.api.deps import get_current_user, get_org_id
from aios.core.business_execution import InMemoryIdempotencyStore


def _app():
    app = FastAPI()
    app.include_router(router)
    app.state.business_idempotency_store = InMemoryIdempotencyStore()
    app.dependency_overrides[get_org_id] = lambda: "org-1"
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1", role="admin")
    return app


@pytest.mark.asyncio
async def test_api_fail_closed_by_default(monkeypatch):
    import aios.api.business_execution as api_mod

    # Explicit dev opt-out keeps this test focused on adapter approval fail-closed.
    monkeypatch.setattr(
        api_mod,
        "settings",
        SimpleNamespace(business_idempotency_required=False),
    )
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/internal/business-execution/execute",
            json={
                "adapter": "email_resend",
                "action": "send_email",
                "payload": {"to": "u@example.test", "subject": "s", "body": "b"},
                "idempotency_key": "idem-api-denied",
            },
        )
    assert resp.status_code == 403
    assert "not approved" in resp.text or "not configured" in resp.text


@pytest.mark.asyncio
async def test_api_rejects_payload_org_mismatch(monkeypatch):
    import aios.api.business_execution as api_mod

    monkeypatch.setattr(
        api_mod,
        "settings",
        SimpleNamespace(business_idempotency_required=False),
    )
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/internal/business-execution/execute",
            json={
                "adapter": "email_resend",
                "action": "send_email",
                "payload": {"org_id": "other-org", "to": "u@example.test", "subject": "s", "body": "b"},
                "idempotency_key": "idem-org-mismatch",
            },
        )
    assert resp.status_code == 403
    assert "payload.org_id must match" in resp.text


@pytest.mark.asyncio
async def test_api_approved_executes_and_dedupes(monkeypatch):
    import aios.api.business_execution as api_mod
    import aios.core.business_execution_service as svc_mod

    sent = []

    def sender(**kw):
        sent.append(kw)
        return {"id": "msg-1"}

    settings = SimpleNamespace(
        execution_approved_adapters="email_resend",
        resend_api_key="rk-test",
        resend_from_email="sandbox@aios.local",
        business_idempotency_required=False,
    )
    monkeypatch.setattr(api_mod, "settings", settings)
    real_build = svc_mod.build_business_execution_registry

    def build(*, settings=None, db=None, audit_callback=None, sandbox_senders=None, approved_adapters=None, idempotency_store=None, require_durable_idempotency=False, require_org_scope=False):
        reg = real_build(
            settings=settings,
            db=db,
            audit_callback=audit_callback,
            sandbox_senders={"email_resend": sender},
            approved_adapters=approved_adapters,
            idempotency_store=idempotency_store,
            require_durable_idempotency=require_durable_idempotency,
            require_org_scope=require_org_scope,
        )
        return reg

    monkeypatch.setattr(svc_mod, "build_business_execution_registry", build)

    app = _app()
    body = {
        "adapter": "email_resend",
        "action": "send_email",
        "payload": {"to": "u@example.test", "subject": "s", "body": "b"},
        "idempotency_key": "idem-api-ok",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        first = await c.post("/api/internal/business-execution/execute", json=body)
        second = await c.post("/api/internal/business-execution/execute", json=body)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["status"] == "ok"
    assert second.json()["status"] in ("duplicate", "ok")  # replayed stored result on durable path
    assert second.json().get("data", {}).get("duplicate") is True or second.json()["status"] == "duplicate"
    assert len(sent) == 1
    assert first.json()["idempotency_durable"] is False  # in-memory app.state store


@pytest.mark.asyncio
async def test_api_reports_durable_when_db_store(monkeypatch, tmp_path):
    import aios.api.business_execution as api_mod
    import aios.core.business_execution_service as svc_mod
    from aios.core.business_idempotency import DBIdempotencyStore

    sent = []

    def sender(**kw):
        sent.append(kw)
        return {"id": "msg-1"}

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'api.db'}"
    store = DBIdempotencyStore.from_settings(SimpleNamespace(database_url=db_url))
    settings = SimpleNamespace(
        execution_approved_adapters="email_resend",
        resend_api_key="rk-test",
        resend_from_email="sandbox@aios.local",
        database_url=db_url,
    )
    monkeypatch.setattr(api_mod, "settings", settings)
    real_build = svc_mod.build_business_execution_registry

    def build(*, settings=None, db=None, audit_callback=None, sandbox_senders=None, approved_adapters=None, idempotency_store=None, require_durable_idempotency=False, require_org_scope=False):
        return real_build(
            settings=settings, db=db, audit_callback=audit_callback,
            sandbox_senders={"email_resend": sender},
            approved_adapters=approved_adapters, idempotency_store=idempotency_store,
            require_durable_idempotency=require_durable_idempotency,
            require_org_scope=require_org_scope,
        )

    monkeypatch.setattr(svc_mod, "build_business_execution_registry", build)

    app = _app()
    app.state.business_idempotency_store = store
    body = {
        "adapter": "email_resend",
        "action": "send_email",
        "payload": {"to": "u@example.test", "subject": "s", "body": "b"},
        "idempotency_key": "idem-api-durable",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        first = await c.post("/api/internal/business-execution/execute", json=body)
        second = await c.post("/api/internal/business-execution/execute", json=body)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["idempotency_durable"] is True
    assert second.json()["status"] == "ok"
    assert second.json()["data"]["duplicate"] is True
    assert second.json()["data"]["durable"] is True
    assert len(sent) == 1
