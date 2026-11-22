"""Process conformance supervision: deterministic deviation detection.

Checks skipped steps, tool misuse, missing approvals, invalid outputs, limits
and escalation. Classifies deviations; root-cause analysis comes later, not here.
"""

from __future__ import annotations

DEVIATION_TYPES = (
    "execution_deviation",
    "process_defect",
    "policy_violation",
    "environmental_failure",
)


def check_conformance(
    *,
    steps_expected: list[str],
    steps_executed: list[str],
    approvals_required: int = 0,
    approvals_done: int = 0,
    tools_allowed: list[str] | None = None,
    tools_used: list[str] | None = None,
    limits_exceeded: bool = False,
    outputs_valid: bool = True,
    exception_occurred: bool = False,
    escalated: bool = False,
) -> tuple[str | None, list[str]]:
    """Return (deviation_type, findings). Deterministic, no LLM authority."""
    findings: list[str] = []
    allowed = set(tools_allowed or [])
    used = set(tools_used or [])
    skipped = [s for s in steps_expected if s not in steps_executed]

    if skipped:
        findings.append(f"skipped steps: {skipped}")
    if not outputs_valid:
        findings.append("invalid output")
    if tools_used is not None and tools_used and not used.issubset(allowed):
        findings.append(f"tool outside allowlist: {sorted(used - allowed)}")
    if approvals_required > approvals_done:
        findings.append("missing approval")
    if limits_exceeded:
        findings.append("limit exceeded")
    if exception_occurred and not escalated:
        findings.append("un-escalated exception")

    if "missing approval" in " ".join(findings):
        return "policy_violation", findings
    if "limit exceeded" in " ".join(findings):
        return "policy_violation", findings
    if "tool outside allowlist" in " ".join(findings):
        return "policy_violation", findings
    if "invalid output" in " ".join(findings):
        return "execution_deviation", findings
    if "skipped steps" in " ".join(findings) or "un-escalated exception" in " ".join(findings):
        return "execution_deviation", findings
    if findings:
        return "process_defect", findings
    return None, findings
