"""Idempotent checkpoint helpers for ICM-X stage attempts.

Stage attempts are recorded as plain dictionaries so they can be persisted
inside the existing WorkflowRun.outputs JSON column without a new table.
"""
from __future__ import annotations

from typing import Any


def record_stage_attempt(
    attempts: dict[str, Any],
    node_id: str,
    provenance: dict[str, Any],
    status: str = "done",
) -> dict[str, Any]:
    """Record an attempt only once per (node, manifest fingerprint).

    Re-running the same stage with the same manifest fingerprint is a no-op,
    which keeps restart recovery from duplicating side-effecting work.
    """
    prior = attempts.get(node_id)
    fingerprint = provenance.get("manifest_fingerprint")
    if prior and prior.get("manifest_fingerprint") == fingerprint and prior.get("status") == "done":
        return prior
    attempt = dict(provenance)
    attempt["status"] = status
    attempts[node_id] = attempt
    return attempt


def load_stage_attempts(outputs: dict[str, Any] | None) -> dict[str, Any]:
    raw = (outputs or {}).get("_icm_stage_attempts")
    if isinstance(raw, dict):
        return dict(raw)
    return {}


def bind_approval(attempt: dict[str, Any], approval_id: str) -> dict[str, Any]:
    """Bind an approval decision to the exact artifact/manifest version."""
    attempt = dict(attempt)
    attempt["approval_id"] = approval_id
    attempt["approved_fingerprint"] = attempt.get("manifest_fingerprint")
    return attempt


def invalidate_dependents(changed_stage_id: str, dependents: dict[str, list[str]]) -> set[str]:
    """Return all stages that must rerun when ``changed_stage_id`` changes.

    ``dependents`` maps a stage id to the stage ids that directly depend on it.
    Transitive dependents are included; the changed stage itself is excluded.
    """
    result: set[str] = set()
    stack = list(dependents.get(changed_stage_id, []))
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.add(current)
        stack.extend(dependents.get(current, []))
    return result


def record_run_metrics(metrics: dict[str, Any], **values: Any) -> dict[str, Any]:
    """Merge per-run ICM-X metrics (cost, latency, tokens, outcomes)."""
    for key, value in values.items():
        metrics[key] = value
    return metrics
