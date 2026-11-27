"""Smoke tests for additive finance/legal system-of-record models."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from aios.db.models import (
    FinanceContract,
    FinanceContractVersion,
    FinanceInvoice,
    FinanceInvoiceLine,
    FinanceLedgerEntry,
    FinancePayment,
    FinanceRefund,
)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_finance_sor_models_smoke(test_session, test_org):
    contract = FinanceContract(
        org_id=test_org.id,
        external_id="ext-c-1",
        contract_number="C-001",
        customer_name="Acme",
        status="draft",
        idempotency_key="contract:k1",
    )
    test_session.add(contract)
    await test_session.flush()

    version = FinanceContractVersion(
        org_id=test_org.id,
        contract_id=contract.id,
        version_number=1,
        status="draft",
        title="MSA",
        amount_minor=10000,
        currency="BRL",
        idempotency_key="cver:k1",
    )
    test_session.add(version)
    await test_session.flush()
    contract.current_version_id = version.id

    invoice = FinanceInvoice(
        org_id=test_org.id,
        external_id="ext-i-1",
        invoice_number="INV-001",
        contract_id=contract.id,
        contract_version_id=version.id,
        status="issued",
        currency="BRL",
        subtotal_minor=10000,
        tax_minor=0,
        total_minor=10000,
        amount_due_minor=10000,
        idempotency_key="inv:k1",
        issued_at=_now(),
    )
    test_session.add(invoice)
    await test_session.flush()

    line = FinanceInvoiceLine(
        org_id=test_org.id,
        invoice_id=invoice.id,
        line_no=1,
        description="Service",
        quantity=1,
        unit_amount_minor=10000,
        line_amount_minor=10000,
        tax_minor=0,
        currency="BRL",
        idempotency_key="line:k1",
    )
    test_session.add(line)
    await test_session.flush()

    payment = FinancePayment(
        org_id=test_org.id,
        external_id="ext-p-1",
        invoice_id=invoice.id,
        provider="manual",
        provider_payment_id="pay_1",
        status="succeeded",
        amount_minor=10000,
        currency="BRL",
        idempotency_key="pay:k1",
        paid_at=_now(),
    )
    test_session.add(payment)
    await test_session.flush()

    refund = FinanceRefund(
        org_id=test_org.id,
        external_id="ext-r-1",
        payment_id=payment.id,
        invoice_id=invoice.id,
        provider="manual",
        provider_refund_id="re_1",
        status="succeeded",
        amount_minor=1000,
        currency="BRL",
        reason="partial",
        idempotency_key="ref:k1",
        refunded_at=_now(),
    )
    test_session.add(refund)
    await test_session.flush()

    entry = FinanceLedgerEntry(
        org_id=test_org.id,
        external_id="ext-l-1",
        entry_type="payment",
        direction="credit",
        account_code="cash",
        amount_minor=10000,
        currency="BRL",
        invoice_id=invoice.id,
        payment_id=payment.id,
        source_system="aios",
        source_ref="pay_1",
        idempotency_key="led:k1",
        occurred_at=_now(),
        posted_at=_now(),
    )
    test_session.add(entry)
    await test_session.commit()

    assert contract.id
    assert version.contract_id == contract.id
    assert invoice.contract_version_id == version.id
    assert line.invoice_id == invoice.id
    assert payment.invoice_id == invoice.id
    assert refund.payment_id == payment.id
    assert entry.payment_id == payment.id


@pytest.mark.asyncio
async def test_finance_invoice_line_unique_per_invoice(test_session, test_org):
    invoice = FinanceInvoice(org_id=test_org.id, status="draft", currency="BRL")
    test_session.add(invoice)
    await test_session.flush()
    test_session.add(FinanceInvoiceLine(org_id=test_org.id, invoice_id=invoice.id, line_no=1))
    await test_session.flush()
    test_session.add(FinanceInvoiceLine(org_id=test_org.id, invoice_id=invoice.id, line_no=1))
    with pytest.raises(IntegrityError):
        await test_session.flush()
    await test_session.rollback()


@pytest.mark.asyncio
async def test_finance_contract_idempotency_unique_per_org(test_session, test_org):
    test_session.add(FinanceContract(org_id=test_org.id, idempotency_key="same"))
    await test_session.flush()
    test_session.add(FinanceContract(org_id=test_org.id, idempotency_key="same"))
    with pytest.raises(IntegrityError):
        await test_session.flush()
    await test_session.rollback()
