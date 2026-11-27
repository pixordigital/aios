from types import SimpleNamespace

import pytest

from aios.core.adapters.registry import build_business_execution_registry
from aios.core.business_execution import ExecutionDenied


NEW_ADAPTERS = [
    ("contract_esign", "create_envelope", "AIOS_CONTRACT_ESIGN_API_KEY"),
    ("payroll_provider", "get_employee", "AIOS_PAYROLL_PROVIDER_API_KEY"),
    ("tax_fiscal", "get_tax_document", "AIOS_TAX_FISCAL_API_KEY"),
]


@pytest.mark.parametrize("name,action,_missing", NEW_ADAPTERS)
def test_new_rails_default_unapproved_fail_closed(name: str, action: str, _missing: str):
    registry = build_business_execution_registry()
    adapter = registry.get(name)
    assert adapter is not None
    assert adapter.approved is False

    with pytest.raises(ExecutionDenied, match="not approved"):
        registry.execute(
            adapter=name,
            action=action,
            payload={"org_id": "org1"},
            idempotency_key=f"idem-{name}-denied",
        )


@pytest.mark.parametrize("name,action,missing_key", NEW_ADAPTERS)
def test_new_rails_requested_without_sandbox_reports_missing(name: str, action: str, missing_key: str):
    settings = SimpleNamespace(**{f"execution_adapter_{name}_approved": True})
    registry = build_business_execution_registry(settings=settings)
    adapter = registry.get(name)
    assert adapter is not None
    assert adapter.approved is False
    assert missing_key in registry.missing_config.get(name, [])


@pytest.mark.parametrize("name,action,_missing", NEW_ADAPTERS)
def test_new_rails_sandbox_sender_executes_stub(name: str, action: str, _missing: str):
    sent: list[dict] = []

    def sandbox_sender(**kw):
        sent.append(dict(kw))
        return {"id": f"{name}-stub-1"}

    settings = SimpleNamespace(execution_approved_adapters=name)
    registry = build_business_execution_registry(settings=settings, sandbox_senders={name: sandbox_sender})
    adapter = registry.get(name)
    assert adapter is not None
    assert adapter.approved is True
    assert getattr(adapter, "sandbox_mode", False) is True

    result = registry.execute(
        adapter=name,
        action=action,
        payload={"org_id": "org1", "ref": "x"},
        idempotency_key=f"idem-{name}-ok",
    )

    assert result.ok is True
    assert result.status == "sandbox_stub"
    assert result.data["sandbox"] is True
    assert result.data["stub"] is True
    assert result.data["provider"] == name
    assert len(sent) == 1
    assert sent[0]["idempotency_key"] == f"idem-{name}-ok"


@pytest.mark.parametrize("name,action,_missing", NEW_ADAPTERS)
def test_new_rails_missing_idempotency_fail_closed(name: str, action: str, _missing: str):
    settings = SimpleNamespace(execution_approved_adapters=name)
    registry = build_business_execution_registry(settings=settings, sandbox_senders={name: lambda **_: {"id": "1"}})
    adapter = registry.get(name)
    assert adapter is not None and adapter.approved is True
    with pytest.raises(ExecutionDenied, match="idempotency_key required"):
        adapter.execute(action=action, payload={"org_id": "org1"}, idempotency_key="")


@pytest.mark.parametrize("name,_action,_missing", NEW_ADAPTERS)
def test_new_rails_unsupported_action_fail_closed(name: str, _action: str, _missing: str):
    settings = SimpleNamespace(execution_approved_adapters=name)
    registry = build_business_execution_registry(settings=settings, sandbox_senders={name: lambda **_: {"id": "1"}})
    adapter = registry.get(name)
    assert adapter is not None
    with pytest.raises(ExecutionDenied, match="unsupported action"):
        adapter.execute(action="delete_everything", payload={"org_id": "org1"}, idempotency_key="idem-bad")
