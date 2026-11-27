from __future__ import annotations

from types import SimpleNamespace

import pytest

from aios.core.adapters.accounting_erp import AccountingErpAdapter
from aios.core.adapters.fiscal_provider import FiscalProviderAdapter
from aios.core.adapters.registry import build_business_execution_registry
from aios.core.business_execution import ExecutionDenied


def test_accounting_erp_fail_closed_by_default():
    adapter = AccountingErpAdapter()
    with pytest.raises(ExecutionDenied, match="not_configured"):
        adapter.execute(action="sync_invoice", payload={"invoice_id": "inv-1"}, idempotency_key="idem-erp-1")


def test_accounting_erp_requires_approval_and_sandbox():
    adapter = AccountingErpAdapter(
        approved=False,
        sandbox_mode=False,
        config={"ACCOUNTING_ERP_API_KEY": "k", "ACCOUNTING_ERP_BASE_URL": "https://sandbox.erp.local"},
        sender=lambda **_: {"ok": True},
    )
    with pytest.raises(ExecutionDenied, match="explicit approval and sandbox_mode"):
        adapter.execute(action="sync_invoice", payload={}, idempotency_key="idem-erp-2")


def test_accounting_erp_sandbox_stub_executes_without_external_calls():
    calls = []
    audit = []

    def sender(*, action, payload, idempotency_key):
        calls.append({"action": action, "payload": payload, "idempotency_key": idempotency_key})
        return {"synced": True}

    adapter = AccountingErpAdapter(
        approved=True,
        sandbox_mode=True,
        config={"ACCOUNTING_ERP_API_KEY": "k", "ACCOUNTING_ERP_BASE_URL": "https://sandbox.erp.local"},
        sender=sender,
        audit_callback=audit.append,
    )
    result = adapter.execute(action="sync_invoice", payload={"invoice_id": "inv-1"}, idempotency_key="idem-erp-ok")

    assert result.ok is True
    assert result.adapter == "accounting_erp"
    assert result.status == "sandbox_stub"
    assert result.data["stub"] is True
    assert result.data["sandbox"] is True
    assert calls == [{"action": "sync_invoice", "payload": {"invoice_id": "inv-1"}, "idempotency_key": "idem-erp-ok"}]
    assert any(e["event"] == "accounting_erp.start" for e in audit)
    assert any(e["event"] == "accounting_erp.result" for e in audit)


def test_fiscal_provider_fail_closed_by_default():
    adapter = FiscalProviderAdapter()
    with pytest.raises(ExecutionDenied, match="not_configured"):
        adapter.execute(action="issue_document_stub", payload={"doc": "nfe"}, idempotency_key="idem-fiscal-1")


def test_fiscal_provider_requires_approval_and_sandbox():
    adapter = FiscalProviderAdapter(
        approved=False,
        sandbox_mode=False,
        config={"FISCAL_PROVIDER_API_KEY": "k", "FISCAL_PROVIDER_BASE_URL": "https://sandbox.fiscal.local"},
        sender=lambda **_: {"ok": True},
    )
    with pytest.raises(ExecutionDenied, match="explicit approval and sandbox_mode"):
        adapter.execute(action="issue_document_stub", payload={}, idempotency_key="idem-fiscal-2")


def test_fiscal_provider_sandbox_stub_executes_without_real_emission():
    calls = []

    def sender(*, action, payload, idempotency_key):
        calls.append({"action": action, "payload": payload, "idempotency_key": idempotency_key})
        return {"status": "stubbed"}

    adapter = FiscalProviderAdapter(
        approved=True,
        sandbox_mode=True,
        config={"FISCAL_PROVIDER_API_KEY": "k", "FISCAL_PROVIDER_BASE_URL": "https://sandbox.fiscal.local"},
        sender=sender,
    )
    result = adapter.execute(action="get_document_status", payload={"doc_id": "d1"}, idempotency_key="idem-fiscal-ok")

    assert result.ok is True
    assert result.adapter == "fiscal_provider"
    assert result.status == "sandbox_stub"
    assert result.data["stub"] is True
    assert "no real fiscal/NF-e/tax call made" in result.detail
    assert len(calls) == 1


def test_registry_registers_new_adapters_fail_closed():
    registry = build_business_execution_registry()
    for name in ("accounting_erp", "fiscal_provider"):
        adapter = registry.get(name)
        assert adapter is not None
        assert adapter.approved is False
        with pytest.raises(ExecutionDenied, match="adapter not approved"):
            registry.execute(adapter=name, action="get_sync_status" if name == "accounting_erp" else "get_document_status", payload={}, idempotency_key=f"idem-{name}")


def test_registry_accounting_erp_requires_sandbox_mode():
    settings = SimpleNamespace(
        execution_adapter_accounting_erp_approved=True,
        accounting_erp_api_key="k",
        accounting_erp_base_url="https://erp.example",
        accounting_erp_sandbox_mode=False,
    )
    registry = build_business_execution_registry(settings=settings)
    adapter = registry.get("accounting_erp")
    assert adapter is not None and adapter.approved is False
    assert "AIOS_ACCOUNTING_ERP_SANDBOX_MODE/sandbox sender" in registry.missing_config.get("accounting_erp", [])


def test_registry_fiscal_sandbox_sender_approved_executes_stub():
    calls = []
    settings = SimpleNamespace(execution_approved_adapters="fiscal_provider")
    registry = build_business_execution_registry(
        settings=settings,
        sandbox_senders={"fiscal_provider": lambda **kw: calls.append(kw) or {"ok": True}},
    )
    adapter = registry.get("fiscal_provider")
    assert adapter is not None and adapter.approved is True

    result = registry.execute(
        adapter="fiscal_provider",
        action="issue_document_stub",
        payload={"doc_type": "nfe"},
        idempotency_key="idem-fiscal-reg",
    )
    assert result.ok is True
    assert result.status == "sandbox_stub"
    assert len(calls) == 1
