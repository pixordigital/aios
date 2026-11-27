"""Business capability registry.

Honest, fail-closed view of real integrations. Nothing is assumed wired;
capabilities must be explicitly marked configured before they can be used.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib.util import find_spec
from typing import Literal

CapabilityStatus = Literal["not_configured", "stub", "schema_only", "draft_configured", "configured"]


@dataclass(frozen=True)
class Capability:
    name: str
    domain: str
    status: CapabilityStatus = "not_configured"
    requires_human: bool = True
    notes: str = ""
    execution_allowed: bool = False  # explicit; never true for SOR-only/internal-draft

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CapabilityDecision:
    name: str
    allowed: bool
    status: CapabilityStatus | str
    requires_human: bool
    reason: str
    execution_allowed: bool = False


def _finance_sor_status() -> tuple[CapabilityStatus, str]:
    """Truthful read-only finance SOR status from code/schema presence.

    No provider rails, no money movement, no autonomous execution.
    """
    model_names = (
        "FinanceContract",
        "FinanceInvoice",
        "FinancePayment",
        "FinanceLedgerEntry",
    )
    try:
        from aios.db import models as db_models

        schema_present = all(hasattr(db_models, n) for n in model_names)
    except Exception:
        schema_present = False
    service_present = find_spec("aios.core.finance_sor") is not None
    if schema_present and service_present:
        return (
            "draft_configured",
            "Internal finance SOR schema+service present (draft). No provider rails, no money movement; execution fail-closed.",
        )
    if schema_present or service_present:
        return (
            "schema_only",
            "Finance SOR partially present in code/schema. No provider rails, no money movement; execution fail-closed.",
        )
    return (
        "not_configured",
        "No finance SOR schema/service wired.",
    )


def _default_capabilities() -> dict[str, Capability]:
    fin_status, fin_note = _finance_sor_status()
    base = [
        ("payment", "payments", "not_configured", "No real payment provider wired."),
        ("crm_writeback", "crm", "not_configured", "No real CRM writeback integration wired."),
        ("email", "messaging", "not_configured", "No real email provider wired."),
        ("sms_whatsapp", "messaging", "not_configured", "No real SMS/WhatsApp integration wired."),
        ("calendar", "scheduling", "not_configured", "No real calendar integration wired."),
        ("fulfillment", "operations", "not_configured", "No real fulfillment integration wired."),
        ("invoicing", "finance", "not_configured", "No real invoicing provider wired."),
        ("finance_contracts", "finance_sor", fin_status, fin_note),
        ("finance_invoices", "finance_sor", fin_status, fin_note),
        ("finance_payments", "finance_sor", fin_status, fin_note),
        ("finance_ledger", "finance_sor", fin_status, fin_note),
    ]
    return {
        name: Capability(
            name=name,
            domain=domain,
            status=status,  # type: ignore[arg-type]
            requires_human=True,
            notes=notes,
            execution_allowed=False,
        )
        for name, domain, status, notes in base
    }


DEFAULT_CAPABILITIES: dict[str, Capability] = _default_capabilities()


def capability_matrix(registry: dict[str, Capability] | None = None) -> list[Capability]:
    """Return honest status for all known capabilities."""
    reg = DEFAULT_CAPABILITIES if registry is None else registry
    return [reg[name] for name in sorted(reg)]


def check_capability(name: str, registry: dict[str, Capability] | None = None) -> CapabilityDecision:
    """Fail closed for execution unless capability explicitly configured.

    `allowed` means real side-effect execution/integration may proceed under
    normal governance. Internal draft/schema-only SOR presence is never enough.
    """
    reg = DEFAULT_CAPABILITIES if registry is None else registry
    cap = reg.get(name)
    if cap is None:
        return CapabilityDecision(
            name=name,
            allowed=False,
            status="not_configured",
            requires_human=True,
            reason=f"Unknown capability '{name}': fail closed.",
            execution_allowed=False,
        )
    if cap.status != "configured":
        if cap.status in {"draft_configured", "schema_only"}:
            reason = (
                f"Capability '{cap.name}' is {cap.status}; internal SOR/schema only. "
                "No provider rails, no money movement. Execution fail-closed."
            )
        else:
            reason = f"Capability '{cap.name}' is {cap.status}; real integration not wired."
        return CapabilityDecision(
            name=cap.name,
            allowed=False,
            status=cap.status,
            requires_human=cap.requires_human,
            reason=reason,
            execution_allowed=False,
        )
    return CapabilityDecision(
        name=cap.name,
        allowed=True,
        status=cap.status,
        requires_human=cap.requires_human,
        reason=f"Capability '{cap.name}' explicitly configured.",
        execution_allowed=bool(cap.execution_allowed) if cap.execution_allowed else True,
    )
