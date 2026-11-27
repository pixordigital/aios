import pytest

from aios.core.finance_sor import (
    FinanceSORAccessError,
    FinanceSORValidationError,
    create_finance_record,
    get_finance_record,
    list_finance_records,
)


@pytest.mark.asyncio
async def test_finance_sor_create_list_get_org_scoped(test_session, test_org, second_org):
    c1 = await create_finance_record(
        test_session,
        org_id=test_org.id,
        entity="contract",
        data={"customer_name": "Acme", "status": "draft", "idempotency_key": "c1"},
    )
    await create_finance_record(
        test_session,
        org_id=second_org.id,
        entity="contract",
        data={"customer_name": "Other", "status": "draft"},
    )
    await test_session.commit()

    got = await get_finance_record(test_session, org_id=test_org.id, entity="contract", record_id=c1.id)
    assert got is not None
    assert got.org_id == test_org.id
    assert got.customer_name == "Acme"

    cross = await get_finance_record(test_session, org_id=second_org.id, entity="contract", record_id=c1.id)
    assert cross is None

    listed = await list_finance_records(test_session, org_id=test_org.id, entity="contract")
    assert [r.id for r in listed] == [c1.id]


@pytest.mark.asyncio
async def test_finance_sor_idempotency_dedupes(test_session, test_org):
    first = await create_finance_record(
        test_session,
        org_id=test_org.id,
        entity="invoice",
        data={"status": "draft", "currency": "BRL", "idempotency_key": "inv-same"},
    )
    await test_session.flush()
    second = await create_finance_record(
        test_session,
        org_id=test_org.id,
        entity="invoice",
        data={"status": "draft", "currency": "BRL", "idempotency_key": "inv-same"},
    )
    await test_session.commit()
    assert first.id == second.id

    listed = await list_finance_records(test_session, org_id=test_org.id, entity="invoice")
    assert len(listed) == 1


@pytest.mark.asyncio
async def test_finance_sor_status_validation(test_session, test_org):
    with pytest.raises(FinanceSORValidationError):
        await create_finance_record(
            test_session,
            org_id=test_org.id,
            entity="payment",
            data={"status": "bogus", "amount_minor": 1, "currency": "BRL"},
        )


@pytest.mark.asyncio
async def test_finance_sor_missing_org_fail_closed(test_session, test_org):
    with pytest.raises(FinanceSORAccessError):
        await create_finance_record(test_session, org_id="", entity="contract", data={"status": "draft"})
    with pytest.raises(FinanceSORAccessError):
        await get_finance_record(test_session, org_id=None, entity="contract", record_id="x")
    with pytest.raises(FinanceSORAccessError):
        await list_finance_records(test_session, org_id="  ", entity="contract")


@pytest.mark.asyncio
async def test_finance_sor_rejects_money_movement_fields(test_session, test_org):
    with pytest.raises(FinanceSORValidationError):
        await create_finance_record(
            test_session,
            org_id=test_org.id,
            entity="payment",
            data={"status": "pending", "amount_minor": 1, "currency": "BRL", "capture": True},
        )


@pytest.mark.asyncio
async def test_finance_sor_unknown_entity_rejected(test_session, test_org):
    with pytest.raises(FinanceSORValidationError):
        await create_finance_record(test_session, org_id=test_org.id, entity="bank_transfer", data={})

from aios.core.finance_sor import (
    FinanceSORConflictError,
    get_finance_reconciliation,
    list_finance_reconciliations,
    list_posted_ledger_entries,
    mark_finance_reconciliation,
    post_balanced_ledger_entries,
)


@pytest.mark.asyncio
async def test_finance_sor_posting_balanced_idempotent(test_session, test_org):
    inv = await create_finance_record(
        test_session,
        org_id=test_org.id,
        entity="invoice",
        data={"status": "issued", "currency": "BRL", "total_minor": 12345, "idempotency_key": "inv-post-1"},
    )
    await test_session.flush()

    r1 = await post_balanced_ledger_entries(
        test_session, org_id=test_org.id, source_entity="invoice", source_id=inv.id, idempotency_key="post:inv:1"
    )
    await test_session.flush()
    r2 = await post_balanced_ledger_entries(
        test_session, org_id=test_org.id, source_entity="invoice", source_id=inv.id, idempotency_key="post:inv:1"
    )
    await test_session.commit()

    assert r1["ok"] is True
    assert r1["deduped"] is False
    assert r1["balanced"] is True
    assert r1["debit_minor"] == 12345
    assert r1["credit_minor"] == 12345
    assert len(r1["entry_ids"]) == 2
    assert r2["deduped"] is True
    assert r2["entry_ids"] == r1["entry_ids"]

    entries = await list_finance_records(test_session, org_id=test_org.id, entity="ledger_entry")
    assert len(entries) == 2
    assert {e.direction for e in entries} == {"debit", "credit"}


@pytest.mark.asyncio
async def test_finance_sor_posting_fail_closed(test_session, test_org, second_org):
    inv = await create_finance_record(
        test_session, org_id=test_org.id, entity="invoice",
        data={"status": "issued", "currency": "BRL", "total_minor": 100},
    )
    draft = await create_finance_record(
        test_session, org_id=test_org.id, entity="invoice",
        data={"status": "draft", "currency": "BRL", "total_minor": 100},
    )
    other = await create_finance_record(
        test_session, org_id=second_org.id, entity="invoice",
        data={"status": "issued", "currency": "BRL", "total_minor": 100},
    )
    await test_session.flush()

    with pytest.raises(FinanceSORAccessError):
        await post_balanced_ledger_entries(
            test_session, org_id=test_org.id, source_entity="invoice", source_id=other.id, idempotency_key="x1"
        )
    with pytest.raises(FinanceSORAccessError):
        await post_balanced_ledger_entries(
            test_session, org_id=test_org.id, source_entity="invoice", source_id="missing", idempotency_key="x2"
        )
    with pytest.raises(FinanceSORValidationError):
        await post_balanced_ledger_entries(
            test_session, org_id=test_org.id, source_entity="invoice", source_id=draft.id, idempotency_key="x3"
        )
    with pytest.raises(FinanceSORValidationError):
        await post_balanced_ledger_entries(
            test_session, org_id=test_org.id, source_entity="invoice", source_id=inv.id, idempotency_key=""
        )

    # duplicate idempotency key for different source -> conflict
    pay = await create_finance_record(
        test_session, org_id=test_org.id, entity="payment",
        data={"status": "succeeded", "currency": "BRL", "amount_minor": 100},
    )
    await test_session.flush()
    await post_balanced_ledger_entries(
        test_session, org_id=test_org.id, source_entity="invoice", source_id=inv.id, idempotency_key="same-key"
    )
    with pytest.raises(FinanceSORConflictError):
        await post_balanced_ledger_entries(
            test_session, org_id=test_org.id, source_entity="payment", source_id=pay.id, idempotency_key="same-key"
        )


@pytest.mark.asyncio
async def test_finance_sor_posting_imbalance_and_invalid_fail_closed(test_session, test_org):
    from aios.core.finance_sor import _validate_balanced_entries

    with pytest.raises(FinanceSORValidationError):
        _validate_balanced_entries([
            {"direction": "debit", "amount_minor": 100, "currency": "BRL"},
            {"direction": "credit", "amount_minor": 99, "currency": "BRL"},
        ])
    with pytest.raises(FinanceSORValidationError):
        _validate_balanced_entries([
            {"direction": "debit", "amount_minor": 100, "currency": "BRL"},
            {"direction": "credit", "amount_minor": 100, "currency": "USD"},
        ])

    # invalid source refs / status handled by public API
    inv = await create_finance_record(
        test_session, org_id=test_org.id, entity="invoice",
        data={"status": "issued", "currency": "BRL", "total_minor": 0},
    )
    await test_session.flush()
    with pytest.raises(FinanceSORValidationError):
        await post_balanced_ledger_entries(
            test_session, org_id=test_org.id, source_entity="invoice", source_id=inv.id, idempotency_key="badamt"
        )


@pytest.mark.asyncio
async def test_finance_sor_reconciliation_status(test_session, test_org, second_org):
    inv = await create_finance_record(
        test_session, org_id=test_org.id, entity="invoice",
        data={"status": "issued", "currency": "BRL", "total_minor": 50},
    )
    pay = await create_finance_record(
        test_session, org_id=test_org.id, entity="payment",
        data={"status": "succeeded", "currency": "BRL", "amount_minor": 50, "invoice_id": inv.id},
    )
    other = await create_finance_record(
        test_session, org_id=second_org.id, entity="payment",
        data={"status": "succeeded", "currency": "BRL", "amount_minor": 50},
    )
    await test_session.flush()

    r = await mark_finance_reconciliation(
        test_session, org_id=test_org.id, entity="payment", record_id=pay.id,
        state="reconciled", reason="matched invoice", linked_entity="invoice", linked_id=inv.id,
    )
    assert r["reconciliation"]["state"] == "reconciled"
    assert r["reconciliation"]["linked_id"] == inv.id

    got = await get_finance_reconciliation(test_session, org_id=test_org.id, entity="payment", record_id=pay.id)
    assert got["reconciliation"]["state"] == "reconciled"
    assert got["reconciliation"]["reason"] == "matched invoice"

    pending = await get_finance_reconciliation(test_session, org_id=test_org.id, entity="invoice", record_id=inv.id)
    assert pending["reconciliation"]["state"] == "pending"

    with pytest.raises(FinanceSORValidationError):
        await mark_finance_reconciliation(
            test_session, org_id=test_org.id, entity="payment", record_id=pay.id,
            state="bad", reason="x",
        )
    with pytest.raises(FinanceSORValidationError):
        await mark_finance_reconciliation(
            test_session, org_id=test_org.id, entity="payment", record_id=pay.id,
            state="mismatch", reason="",
        )
    with pytest.raises(FinanceSORAccessError):
        await mark_finance_reconciliation(
            test_session, org_id=test_org.id, entity="payment", record_id=other.id,
            state="mismatch", reason="cross org",
        )
    with pytest.raises(FinanceSORAccessError):
        await mark_finance_reconciliation(
            test_session, org_id=test_org.id, entity="payment", record_id=pay.id,
            state="mismatch", reason="bad link", linked_entity="invoice", linked_id=other.id,
        )


@pytest.mark.asyncio
async def test_finance_sor_reconciliation_list_and_ledger_visibility(test_session, test_org, second_org):
    inv = await create_finance_record(
        test_session, org_id=test_org.id, entity="invoice",
        data={"status": "issued", "currency": "BRL", "total_minor": 77},
    )
    pay = await create_finance_record(
        test_session, org_id=test_org.id, entity="payment",
        data={"status": "succeeded", "currency": "BRL", "amount_minor": 77, "invoice_id": inv.id},
    )
    other_inv = await create_finance_record(
        test_session, org_id=second_org.id, entity="invoice",
        data={"status": "issued", "currency": "BRL", "total_minor": 88},
    )
    await test_session.flush()

    await post_balanced_ledger_entries(
        test_session, org_id=test_org.id, source_entity="payment", source_id=pay.id, idempotency_key="post:pay:list"
    )
    await mark_finance_reconciliation(
        test_session, org_id=test_org.id, entity="payment", record_id=pay.id,
        state="reconciled", reason="matched", linked_entity="invoice", linked_id=inv.id,
    )
    await mark_finance_reconciliation(
        test_session, org_id=second_org.id, entity="invoice", record_id=other_inv.id,
        state="mismatch", reason="other org",
    )
    await test_session.commit()

    recs = await list_finance_reconciliations(test_session, org_id=test_org.id, entity="payment")
    assert [r["record_id"] for r in recs] == [pay.id]
    assert recs[0]["reconciliation"]["state"] == "reconciled"

    only_rec = await list_finance_reconciliations(test_session, org_id=test_org.id, state="reconciled")
    assert all(r["reconciliation"]["state"] == "reconciled" for r in only_rec)
    assert all(r["record_id"] != other_inv.id for r in only_rec)

    entries = await list_posted_ledger_entries(
        test_session, org_id=test_org.id, source_entity="payment", source_id=pay.id
    )
    assert len(entries) == 2
    assert {e.direction for e in entries} == {"debit", "credit"}
    assert all((e.extra_data or {}).get("posting_key") == "post:pay:list" for e in entries)

    by_key = await list_posted_ledger_entries(test_session, org_id=test_org.id, posting_key="post:pay:list")
    assert {e.id for e in by_key} == {e.id for e in entries}

    cross = await list_posted_ledger_entries(test_session, org_id=test_org.id, source_entity="invoice", source_id=other_inv.id)
    assert cross == []


@pytest.mark.asyncio
async def test_finance_sor_ledger_visibility_fail_closed(test_session, test_org):
    with pytest.raises(FinanceSORValidationError):
        await list_posted_ledger_entries(test_session, org_id=test_org.id, source_entity="contract")
    with pytest.raises(FinanceSORValidationError):
        await list_posted_ledger_entries(test_session, org_id=test_org.id, source_id="x")
    with pytest.raises(FinanceSORAccessError):
        await list_posted_ledger_entries(test_session, org_id="", source_entity="payment", source_id="x")
    with pytest.raises(FinanceSORValidationError):
        await list_finance_reconciliations(test_session, org_id=test_org.id, state="bad")
