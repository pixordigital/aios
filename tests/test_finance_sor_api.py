import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from aios.api.deps import get_current_user, get_org_id
from aios.api.finance_sor import router
from aios.core.finance_sor import (
    create_finance_record,
    mark_finance_reconciliation,
    post_balanced_ledger_entries,
)
from aios.db.backend import get_db_backend
from aios.db.models import PendingAction


@pytest.fixture
def finance_app(test_db_session, test_org, test_user):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db_backend] = lambda: test_db_session
    app.dependency_overrides[get_current_user] = lambda: test_user
    org_id = test_org.id
    app.dependency_overrides[get_org_id] = lambda: org_id
    return app


@pytest.mark.asyncio
async def test_finance_sor_api_list_get_read_only(finance_app, test_session, test_org):
    c = await create_finance_record(
        test_session, org_id=test_org.id, entity="contract", data={"customer_name": "A", "status": "draft"}
    )
    await test_session.commit()

    async with AsyncClient(transport=ASGITransport(app=finance_app), base_url="http://test") as ac:
        r = await ac.get("/api/internal/finance-sor/contract")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert body["items"][0]["id"] == c.id

        r2 = await ac.get(f"/api/internal/finance-sor/contract/{c.id}")
        assert r2.status_code == 200
        assert r2.json()["customer_name"] == "A"


@pytest.mark.asyncio
async def test_finance_sor_api_cross_org_fail_closed(finance_app, test_session, test_org, second_org):
    other = await create_finance_record(
        test_session, org_id=second_org.id, entity="contract", data={"customer_name": "B", "status": "draft"}
    )
    await test_session.commit()

    async with AsyncClient(transport=ASGITransport(app=finance_app), base_url="http://test") as ac:
        r = await ac.get(f"/api/internal/finance-sor/contract/{other.id}")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_finance_sor_api_rejects_unknown_entity(finance_app):
    async with AsyncClient(transport=ASGITransport(app=finance_app), base_url="http://test") as ac:
        r = await ac.get("/api/internal/finance-sor/bank_transfer")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_finance_sor_api_reconciliation_and_ledger_visibility(finance_app, test_session, test_org, second_org):
    org_id = test_org.id
    other_org_id = second_org.id
    inv = await create_finance_record(
        test_session, org_id=org_id, entity="invoice",
        data={"status": "issued", "currency": "BRL", "total_minor": 55},
    )
    pay = await create_finance_record(
        test_session, org_id=org_id, entity="payment",
        data={"status": "succeeded", "currency": "BRL", "amount_minor": 55, "invoice_id": inv.id},
    )
    other = await create_finance_record(
        test_session, org_id=other_org_id, entity="payment",
        data={"status": "succeeded", "currency": "BRL", "amount_minor": 55},
    )
    await test_session.flush()
    await post_balanced_ledger_entries(
        test_session, org_id=org_id, source_entity="payment", source_id=pay.id, idempotency_key="api:post:1"
    )
    await mark_finance_reconciliation(
        test_session, org_id=org_id, entity="payment", record_id=pay.id,
        state="reconciled", reason="ok", linked_entity="invoice", linked_id=inv.id,
    )
    await post_balanced_ledger_entries(
        test_session, org_id=other_org_id, source_entity="payment", source_id=other.id, idempotency_key="api:post:other"
    )
    await test_session.commit()

    async with AsyncClient(transport=ASGITransport(app=finance_app), base_url="http://test") as ac:
        r = await ac.get("/api/internal/finance-sor/reconciliations", params={"entity": "payment"})
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert body["items"][0]["record_id"] == pay.id
        assert body["items"][0]["reconciliation"]["state"] == "reconciled"

        r2 = await ac.get(f"/api/internal/finance-sor/reconciliations/payment/{pay.id}")
        assert r2.status_code == 200
        assert r2.json()["reconciliation"]["linked_id"] == inv.id

        r3 = await ac.get(f"/api/internal/finance-sor/reconciliations/payment/{other.id}")
        assert r3.status_code == 403

        l = await ac.get("/api/internal/finance-sor/ledger-entries", params={"source_entity": "payment", "source_id": pay.id})
        assert l.status_code == 200
        lb = l.json()
        assert lb["count"] == 2
        assert {i["direction"] for i in lb["items"]} == {"debit", "credit"}
        assert all(i["org_id"] == org_id for i in lb["items"])

        l2 = await ac.get("/api/internal/finance-sor/ledger-entries", params={"source_entity": "payment", "source_id": other.id})
        assert l2.status_code == 200
        assert l2.json()["count"] == 0

        bad = await ac.get("/api/internal/finance-sor/ledger-entries", params={"source_entity": "contract"})
        assert bad.status_code == 400

        bad_state = await ac.get("/api/internal/finance-sor/reconciliations", params={"state": "bogus"})
        assert bad_state.status_code == 400


async def _mk_approval(session, *, org_id: str, tool_name: str, tool_args: dict, status="approved", decided_by="admin-user"):
    row = PendingAction(
        org_id=org_id,
        tool_name=tool_name,
        tool_args=tool_args,
        status=status,
        decided_by=decided_by,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@pytest.mark.asyncio
async def test_finance_sor_api_post_ledger_requires_approval_and_posts(finance_app, test_session, test_org):
    org_id = test_org.id
    inv = await create_finance_record(
        test_session, org_id=org_id, entity="invoice",
        data={"status": "issued", "currency": "BRL", "total_minor": 9900},
    )
    await test_session.commit()
    args = {"source_entity": "invoice", "source_id": inv.id, "idempotency_key": "api-post-1"}

    async with AsyncClient(transport=ASGITransport(app=finance_app), base_url="http://test") as ac:
        missing = await ac.post("/api/internal/finance-sor/ledger/postings", json={**args, "approval_action_id": "missing"})
        assert missing.status_code == 409
        assert missing.json()["detail"]["error"] == "approval_required"

        approval = await _mk_approval(test_session, org_id=org_id, tool_name="finance_sor.post_balanced_ledger_entries", tool_args=args)
        approval_id = approval.id
        ok = await ac.post("/api/internal/finance-sor/ledger/postings", json={**args, "approval_action_id": approval_id})
        assert ok.status_code == 200
        body = ok.json()
        assert body["balanced"] is True
        assert body["deduped"] is False
        assert len(body["entry_ids"]) == 2
        assert body["approval"]["approval_action_id"] == approval_id

        replay = await ac.post("/api/internal/finance-sor/ledger/postings", json={**args, "approval_action_id": approval_id})
        assert replay.status_code == 200
        replay_body = replay.json()
        assert replay_body["deduped"] is True
        assert replay_body["entry_ids"] == body["entry_ids"]


@pytest.mark.asyncio
async def test_finance_sor_api_post_ledger_fail_closed(finance_app, test_session, test_org, second_org):
    org_id = test_org.id
    other_org_id = second_org.id
    inv = await create_finance_record(
        test_session, org_id=other_org_id, entity="invoice",
        data={"status": "issued", "currency": "BRL", "total_minor": 100},
    )
    await test_session.commit()
    args = {"source_entity": "invoice", "source_id": inv.id, "idempotency_key": "cross-org"}
    approval = await _mk_approval(test_session, org_id=org_id, tool_name="finance_sor.post_balanced_ledger_entries", tool_args=args)
    approval_id = approval.id

    async with AsyncClient(transport=ASGITransport(app=finance_app), base_url="http://test") as ac:
        r = await ac.post("/api/internal/finance-sor/ledger/postings", json={**args, "approval_action_id": approval_id})
        assert r.status_code == 403

    # Denied posting rolls back, so approval stays unconsumed and args remain bound to the foreign source.
    refreshed = await test_session.get(PendingAction, approval_id)
    assert refreshed.status == "approved"


@pytest.mark.asyncio
async def test_finance_sor_api_mark_reconciliation_requires_approval(finance_app, test_session, test_org):
    org_id = test_org.id
    inv = await create_finance_record(
        test_session, org_id=org_id, entity="invoice",
        data={"status": "issued", "currency": "BRL", "total_minor": 100},
    )
    await test_session.commit()
    args = {
        "entity": "invoice",
        "record_id": inv.id,
        "state": "reconciled",
        "reason": "manual check",
        "idempotency_key": "recon-1",
    }

    async with AsyncClient(transport=ASGITransport(app=finance_app), base_url="http://test") as ac:
        no_approval = await ac.post("/api/internal/finance-sor/reconciliations/mark", json={**args, "approval_action_id": "x"})
        assert no_approval.status_code == 409

        bad_args_approval = await _mk_approval(
            test_session, org_id=org_id, tool_name="finance_sor.mark_finance_reconciliation",
            tool_args={**args, "state": "mismatch"},
        )
        bad_args_approval_id = bad_args_approval.id
        mismatch = await ac.post("/api/internal/finance-sor/reconciliations/mark", json={**args, "approval_action_id": bad_args_approval_id})
        assert mismatch.status_code == 409

        approval = await _mk_approval(test_session, org_id=org_id, tool_name="finance_sor.mark_finance_reconciliation", tool_args=args)
        approval_id = approval.id
        ok = await ac.post("/api/internal/finance-sor/reconciliations/mark", json={**args, "approval_action_id": approval_id})
        assert ok.status_code == 200
        body = ok.json()
        assert body["reconciliation"]["state"] == "reconciled"
        assert body["approval"]["approval_action_id"] == approval_id

        # same idempotency key + same args => deduped, no new approval consumed
        dedup = await ac.post("/api/internal/finance-sor/reconciliations/mark", json={**args, "approval_action_id": "not-used"})
        assert dedup.status_code == 200
        assert dedup.json()["deduped"] is True
