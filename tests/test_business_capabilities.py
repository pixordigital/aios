from aios.core.business_capabilities import (
    Capability,
    DEFAULT_CAPABILITIES,
    capability_matrix,
    check_capability,
)


EXPECTED_NAMES = {
    "payment",
    "crm_writeback",
    "email",
    "sms_whatsapp",
    "calendar",
    "fulfillment",
    "invoicing",
    "finance_contracts",
    "finance_invoices",
    "finance_payments",
    "finance_ledger",
}


def test_default_capabilities_truthful_status():
    assert set(DEFAULT_CAPABILITIES) == EXPECTED_NAMES
    for cap in DEFAULT_CAPABILITIES.values():
        assert cap.requires_human is True
        assert cap.execution_allowed is False
    for name in ["payment", "crm_writeback", "email", "sms_whatsapp", "calendar", "fulfillment", "invoicing"]:
        assert DEFAULT_CAPABILITIES[name].status == "not_configured"
    for name in ["finance_contracts", "finance_invoices", "finance_payments", "finance_ledger"]:
        assert DEFAULT_CAPABILITIES[name].status in {"draft_configured", "schema_only"}
        assert "no money movement" in DEFAULT_CAPABILITIES[name].notes.lower()


def test_check_capability_fails_closed_for_non_configured():
    for name in EXPECTED_NAMES:
        decision = check_capability(name)
        assert decision.allowed is False
        assert decision.execution_allowed is False
        assert decision.name == name
        assert decision.status in {"not_configured", "draft_configured", "schema_only"}
        if decision.status in {"draft_configured", "schema_only"}:
            assert "no money movement" in decision.reason.lower()
            assert "fail-closed" in decision.reason.lower() or "fail closed" in decision.reason.lower()
        else:
            assert "not_configured" in decision.reason or "not wired" in decision.reason


def test_matrix_contains_all_domains():
    matrix = capability_matrix()
    names = {cap.name for cap in matrix}
    domains = {cap.domain for cap in matrix}
    assert names == EXPECTED_NAMES
    assert domains == {"payments", "crm", "messaging", "scheduling", "operations", "finance", "finance_sor"}
    assert all(cap.execution_allowed is False for cap in matrix)


def test_configured_capability_allowed_only_if_explicitly_marked():
    registry = {
        "payment": Capability(
            name="payment",
            domain="payments",
            status="configured",
            requires_human=False,
            notes="Explicitly wired in test.",
        )
    }
    allowed = check_capability("payment", registry=registry)
    assert allowed.allowed is True
    assert allowed.status == "configured"
    assert allowed.requires_human is False
    assert allowed.execution_allowed is True

    not_configured = check_capability("payment")  # default registry
    assert not_configured.allowed is False
    assert not_configured.status == "not_configured"
    assert not_configured.execution_allowed is False


def test_unknown_capability_fails_closed():
    decision = check_capability("nonexistent_capability")
    assert decision.allowed is False
    assert decision.status == "not_configured"
    assert "fail closed" in decision.reason.lower()


def test_finance_sor_draft_configured_never_allows_execution():
    for name in ["finance_contracts", "finance_invoices", "finance_payments", "finance_ledger"]:
        decision = check_capability(name)
        assert decision.status in {"draft_configured", "schema_only"}
        assert decision.allowed is False
        assert decision.execution_allowed is False
        assert "no provider rails" in decision.reason.lower() or "no money movement" in decision.reason.lower()
