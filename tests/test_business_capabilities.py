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
}


def test_default_capabilities_not_configured():
    assert set(DEFAULT_CAPABILITIES) == EXPECTED_NAMES
    for cap in DEFAULT_CAPABILITIES.values():
        assert cap.status == "not_configured"
        assert cap.requires_human is True


def test_check_capability_fails_closed_for_not_configured():
    for name in EXPECTED_NAMES:
        decision = check_capability(name)
        assert decision.allowed is False
        assert decision.status == "not_configured"
        assert decision.name == name
        assert "not_configured" in decision.reason or "not wired" in decision.reason


def test_matrix_contains_all_domains():
    matrix = capability_matrix()
    names = {cap.name for cap in matrix}
    domains = {cap.domain for cap in matrix}
    assert names == EXPECTED_NAMES
    assert domains == {"payments", "crm", "messaging", "scheduling", "operations", "finance"}
    assert all(cap.status == "not_configured" for cap in matrix)


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

    not_configured = check_capability("payment")  # default registry
    assert not_configured.allowed is False
    assert not_configured.status == "not_configured"


def test_unknown_capability_fails_closed():
    decision = check_capability("nonexistent_capability")
    assert decision.allowed is False
    assert decision.status == "not_configured"
    assert "fail closed" in decision.reason.lower()
