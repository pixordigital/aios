from dataclasses import dataclass, field
from typing import Any

import pytest

from aios.core.business_execution import (
    ExecutionDenied,
    ExecutionRegistry,
    ExecutionResult,
)


@dataclass
class DryRunAdapter:
    name: str = "dry_run"
    approved: bool = True
    calls: list[dict[str, Any]] = field(default_factory=list)

    def execute(
        self,
        *,
        action: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> ExecutionResult:
        self.calls.append(
            {
                "action": action,
                "payload": dict(payload),
                "idempotency_key": idempotency_key,
            }
        )
        return ExecutionResult(
            ok=True,
            adapter=self.name,
            action=action,
            idempotency_key=idempotency_key,
            status="ok",
            detail="dry-run",
            data={"payload": dict(payload)},
        )


def test_unconfigured_adapter_fails_closed():
    registry = ExecutionRegistry(idempotency_store=None, require_durable_idempotency=False)

    with pytest.raises(ExecutionDenied, match="not configured"):
        registry.execute(
            adapter="missing",
            action="invoice.create",
            payload={"customer": "acme", "org_id": "org1"},
            idempotency_key="idem-1",
        )


def test_unapproved_adapter_fails_closed():
    registry = ExecutionRegistry(idempotency_store=None, require_durable_idempotency=False)
    registry.register(DryRunAdapter(approved=False))

    with pytest.raises(ExecutionDenied, match="not approved"):
        registry.execute(
            adapter="dry_run",
            action="invoice.create",
            payload={"customer": "acme", "org_id": "org1"},
            idempotency_key="idem-2",
        )


def test_idempotency_key_required_for_side_effect():
    registry = ExecutionRegistry(idempotency_store=None, require_durable_idempotency=False)
    registry.register(DryRunAdapter())

    with pytest.raises(ExecutionDenied, match="idempotency_key required"):
        registry.execute(
            adapter="dry_run",
            action="invoice.create",
            payload={"customer": "acme", "org_id": "org1"},
            idempotency_key="",
        )


def test_audit_callback_called():
    events: list[dict[str, Any]] = []
    registry = ExecutionRegistry(
        audit_callback=events.append,
        idempotency_store=None,
        require_durable_idempotency=False,
    )
    registry.register(DryRunAdapter())

    result = registry.execute(
        adapter="dry_run",
        action="invoice.create",
        payload={"customer": "acme", "org_id": "org1"},
        idempotency_key="idem-audit",
    )

    assert result.ok is True
    assert events
    assert any(e.get("event") == "business_execution.start" for e in events)
    assert any(
        e.get("event") == "business_execution.result" and e.get("ok") is True
        for e in events
    )


def test_configured_dry_run_adapter_returns_ok():
    adapter = DryRunAdapter()
    registry = ExecutionRegistry(idempotency_store=None, require_durable_idempotency=False)
    registry.register(adapter)

    result = registry.execute(
        adapter="dry_run",
        action="invoice.create",
        payload={"customer": "acme", "org_id": "org1"},
        idempotency_key="idem-ok",
    )

    assert result.ok is True
    assert result.status == "ok"
    assert result.adapter == "dry_run"
    assert result.action == "invoice.create"
    assert result.idempotency_key == "idem-ok"
    assert adapter.calls == [
        {
            "action": "invoice.create",
            "payload": {"customer": "acme", "org_id": "org1"},
            "idempotency_key": "idem-ok",
        }
    ]
