"""Cross-org/tenant isolation fail-closed tests for new surfaces.

Covers: finance SOR read/mutation, business execution, whatsapp approval consume.
Tests only; no prod data/creds.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from aios.api.business_execution import router as business_router
from aios.api.deps import get_current_user, get_org_id
from aios.api.finance_sor import router as finance_router
from aios.core.business_execution import InMemoryIdempotencyStore
from aios.core.finance_sor import create_finance_record, post_balanced_ledger_entries
from aios.db.backend import get_db_backend
from aios.db.models import AuditLog, ChannelConnection, PendingAction


def _finance_app(db, user, org_id: str):
    app = FastAPI()
    app.include_router(finance_router)
    app.dependency_overrides[get_db_backend] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_org_id] = lambda: org_id
    return app


def _business_app(org_id: str, user):
    app = FastAPI()
    app.include_router(business_router)
    app.state.business_idempotency_store = InMemoryIdempotencyStore()
    app.dependency_overrides[get_org_id] = lambda: org_id
    app.dependency_overrides[get_current_user] = lambda: user
    return app


async def _mk_approval(db, *, org_id: str, tool_name: str, tool_args: dict, status="approved"):
    row = PendingAction(org_id=org_id, tool_name=tool_name, tool_args=tool_args, status=status, decided_by="admin-user")
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def _mk_conn(org_id: str, instance="wa-iso-1"):
    return ChannelConnection(org_id=org_id, channel_type="evolution", label="WA", config={"instance": instance}, is_active=True)


def _patch_send(monkeypatch, calls):
    async def _send(*_a, **_k):
        calls["send"] += 1
        return {"ok": True}

    monkeypatch.setattr("aios.core.whatsapp.service.send_via_gateway", _send)
    monkeypatch.setattr("aios.core.whatsapp.anti_ban.rate_limiter.allow", lambda *_a, **_k: True)
    monkeypatch.setattr("aios.core.whatsapp.anti_ban.rate_limiter.record_429", lambda *_a, **_k: None)

    class _Metric:
        def labels(self, **_k):
            return self

        def inc(self, *_a, **_k):
            return None

    monkeypatch.setattr("aios.core.whatsapp.metrics.msg_total", _Metric())


@pytest.mark.asyncio
async def test_finance_sor_reads_fail_closed_cross_org(test_db_session, test_org, second_org, test_user):
    own = await create_finance_record(
        test_db_session, org_id=test_org.id, entity="contract", data={"customer_name": "own", "status": "draft"}
    )
    foreign = await create_finance_record(
        test_db_session, org_id=second_org.id, entity="contract", data={"customer_name": "foreign", "status": "draft"}
    )
    foreign_inv = await create_finance_record(
        test_db_session, org_id=second_org.id, entity="invoice",
        data={"status": "issued", "currency": "BRL", "total_minor": 100},
    )
    foreign_pay = await create_finance_record(
        test_db_session, org_id=second_org.id, entity="payment",
        data={"status": "succeeded", "currency": "BRL", "amount_minor": 100, "invoice_id": foreign_inv.id},
    )
    await test_db_session.flush()
    await post_balanced_ledger_entries(
        test_db_session, org_id=second_org.id, source_entity="payment", source_id=foreign_pay.id, idempotency_key="iso:foreign"
    )
    await test_db_session.commit()

    app = _finance_app(test_db_session, test_user, test_org.id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        listed = await ac.get("/api/internal/finance-sor/contract")
        assert listed.status_code == 200
        ids = {i["id"] for i in listed.json()["items"]}
        assert own.id in ids
        assert foreign.id not in ids

        got = await ac.get(f"/api/internal/finance-sor/contract/{foreign.id}")
        assert got.status_code == 404

        rec = await ac.get(f"/api/internal/finance-sor/reconciliations/payment/{foreign_pay.id}")
        assert rec.status_code == 403

        rec_list = await ac.get("/api/internal/finance-sor/reconciliations", params={"entity": "payment"})
        assert rec_list.status_code == 200
        assert all(i["record_id"] != foreign_pay.id for i in rec_list.json()["items"])

        ledger = await ac.get("/api/internal/finance-sor/ledger-entries", params={"source_entity": "payment", "source_id": foreign_pay.id})
        assert ledger.status_code == 200
        assert ledger.json()["count"] == 0


@pytest.mark.asyncio
async def test_finance_sor_mutations_fail_closed_cross_org_approval(test_db_session, test_org, second_org, test_user):
    foreign_inv = await create_finance_record(
        test_db_session, org_id=second_org.id, entity="invoice",
        data={"status": "issued", "currency": "BRL", "total_minor": 777},
    )
    await test_db_session.commit()
    args = {"source_entity": "invoice", "source_id": foreign_inv.id, "idempotency_key": "iso-cross-org"}
    foreign_org_approval = await _mk_approval(
        test_db_session, org_id=second_org.id, tool_name="finance_sor.post_balanced_ledger_entries", tool_args=args
    )

    app = _finance_app(test_db_session, test_user, test_org.id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/internal/finance-sor/ledger/postings", json={**args, "approval_action_id": foreign_org_approval.id})
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"] == "approval_required"

    refreshed = await test_db_session.get(PendingAction, foreign_org_approval.id)
    assert refreshed.status == "approved"


@pytest.mark.asyncio
async def test_business_execution_payload_org_mismatch_fail_closed(monkeypatch, test_user):
    import aios.api.business_execution as api_mod

    monkeypatch.setattr(api_mod, "settings", SimpleNamespace(business_idempotency_required=False))
    app = _business_app("org-1", test_user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/internal/business-execution/execute",
            json={
                "adapter": "email_resend",
                "action": "send_email",
                "payload": {"org_id": "org-other", "to": "u@example.test", "subject": "s", "body": "b"},
                "idempotency_key": "iso-biz-mismatch",
            },
        )
    assert resp.status_code == 403
    assert "payload.org_id must match" in resp.text


@pytest.mark.asyncio
async def test_whatsapp_approval_and_instance_cross_org_fail_closed(auth_client, test_db_session, test_org, second_org, monkeypatch):
    test_db_session.add(_mk_conn(test_org.id, instance="wa-own"))
    test_db_session.add(_mk_conn(second_org.id, instance="wa-foreign"))
    await test_db_session.commit()
    calls = {"send": 0}
    _patch_send(monkeypatch, calls)

    foreign_approval = await _mk_approval(
        test_db_session,
        org_id=second_org.id,
        tool_name="whatsapp_template",
        tool_args={"to": "5511999999999", "text": "hi", "instance": "wa-own", "provider": "baileys"},
    )
    cross_org_send = await auth_client.post(
        "/api/whatsapp/send",
        json={
            "instance": "wa-own",
            "to": "5511999999999",
            "text": "hi",
            "provider": "baileys",
            "approval_action_id": foreign_approval.id,
        },
    )
    assert cross_org_send.status_code == 409
    assert calls["send"] == 0
    assert (await test_db_session.get(PendingAction, foreign_approval.id)).status == "approved"

    foreign_instance = await auth_client.post(
        "/api/whatsapp/send",
        json={"instance": "wa-foreign", "to": "5511999999999", "text": "hi", "provider": "baileys"},
    )
    assert foreign_instance.status_code == 404
    assert calls["send"] == 0

    # cross-org call approval also denied
    call_calls = {"call": 0}

    async def _start(*_a, **_k):
        call_calls["call"] += 1
        return {"ok": True}

    monkeypatch.setattr("aios.core.whatsapp.voice.call_router.start_outbound", _start)
    foreign_call_approval = await _mk_approval(
        test_db_session,
        org_id=second_org.id,
        tool_name="voice_call",
        tool_args={"to": "5511999999999", "instance": "wa-own", "script": "hi"},
    )
    cross_org_call = await auth_client.post(
        "/api/whatsapp/call",
        json={"instance": "wa-own", "to": "5511999999999", "script": "hi", "approval_action_id": foreign_call_approval.id},
    )
    assert cross_org_call.status_code == 409
    assert call_calls["call"] == 0
    assert (await test_db_session.get(PendingAction, foreign_call_approval.id)).status == "approved"
