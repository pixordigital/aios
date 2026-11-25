"""Business capability registry.

Honest, fail-closed view of real integrations. Nothing is assumed wired;
capabilities must be explicitly marked configured before they can be used.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CapabilityStatus = Literal["not_configured", "stub", "configured"]


@dataclass(frozen=True)
class Capability:
    name: str
    domain: str
    status: CapabilityStatus = "not_configured"
    requires_human: bool = True
    notes: str = ""


@dataclass(frozen=True)
class CapabilityDecision:
    name: str
    allowed: bool
    status: CapabilityStatus | str
    requires_human: bool
    reason: str


DEFAULT_CAPABILITIES: dict[str, Capability] = {
    name: Capability(name=name, domain=domain, status="not_configured", requires_human=True, notes=notes)
    for name, domain, notes in [
        ("payment", "payments", "No real payment provider wired."),
        ("crm_writeback", "crm", "No real CRM writeback integration wired."),
        ("email", "messaging", "No real email provider wired."),
        ("sms_whatsapp", "messaging", "No real SMS/WhatsApp integration wired."),
        ("calendar", "scheduling", "No real calendar integration wired."),
        ("fulfillment", "operations", "No real fulfillment integration wired."),
        ("invoicing", "finance", "No real invoicing integration wired."),
    ]
}


def capability_matrix(registry: dict[str, Capability] | None = None) -> list[Capability]:
    """Return honest status for all known capabilities."""
    reg = DEFAULT_CAPABILITIES if registry is None else registry
    return [reg[name] for name in sorted(reg)]


def check_capability(name: str, registry: dict[str, Capability] | None = None) -> CapabilityDecision:
    """Fail closed unless capability is explicitly configured."""
    reg = DEFAULT_CAPABILITIES if registry is None else registry
    cap = reg.get(name)
    if cap is None:
        return CapabilityDecision(
            name=name,
            allowed=False,
            status="not_configured",
            requires_human=True,
            reason=f"Unknown capability '{name}': fail closed.",
        )
    if cap.status != "configured":
        return CapabilityDecision(
            name=cap.name,
            allowed=False,
            status=cap.status,
            requires_human=cap.requires_human,
            reason=f"Capability '{cap.name}' is {cap.status}; real integration not wired.",
        )
    return CapabilityDecision(
        name=cap.name,
        allowed=True,
        status=cap.status,
        requires_human=cap.requires_human,
        reason=f"Capability '{cap.name}' explicitly configured.",
    )
