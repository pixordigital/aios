"""Runtime enforcement for ICM-X declared contracts.

A manifest field is not a guarantee until the runtime obeys it. These primitives
close the gaps: per-stage LLM/cost ceilings, retry classification and
duplicate-side-effect protection.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from aios.icm.contracts import RetryPolicy, StageManifest


class BudgetExceeded(RuntimeError):
    """Declared per-stage budget is exhausted."""


class ToolDenied(PermissionError):
    """Tool is outside the stage contract."""


@dataclass
class StageBudget:
    """Deterministic counter checked before every paid call."""

    max_llm_calls: int
    max_cost_usd: float
    calls: int = 0
    cost_usd: float = 0.0
    events: list[dict] = field(default_factory=list)
    max_tool_calls: int = 25
    tool_calls: int = 0

    @classmethod
    def from_manifest(cls, manifest: StageManifest, max_tool_calls: int | None = None) -> "StageBudget":
        return cls(
            max_llm_calls=manifest.max_llm_calls,
            max_cost_usd=manifest.max_cost_usd,
            max_tool_calls=max_tool_calls if max_tool_calls is not None else max(1, manifest.max_llm_calls),
        )

    def can_call(self) -> tuple[bool, str]:
        if self.max_llm_calls <= 0:
            return False, "stage allows no LLM calls"
        if self.calls >= self.max_llm_calls:
            return False, "LLM call ceiling reached"
        if self.cost_usd >= self.max_cost_usd:
            return False, "cost ceiling reached"
        return True, "ok"

    def charge(self, cost_usd: float = 0.0) -> None:
        ok, reason = self.can_call()
        if not ok:
            raise BudgetExceeded(reason)
        if self.cost_usd + cost_usd > self.max_cost_usd:
            raise BudgetExceeded("cost ceiling would be exceeded")
        self.calls += 1
        self.cost_usd = round(self.cost_usd + cost_usd, 8)
        self.events.append({"call": self.calls, "cost_usd": cost_usd})

    def charge_tool(self) -> None:
        if self.tool_calls >= self.max_tool_calls:
            raise BudgetExceeded("tool ceiling reached")
        self.tool_calls += 1

    @property
    def remaining_calls(self) -> int:
        return max(0, self.max_llm_calls - self.calls)

    @property
    def remaining_usd(self) -> float:
        return max(0.0, round(self.max_cost_usd - self.cost_usd, 8))


def check_tool(manifest: StageManifest, tool_name: str) -> None:
    if tool_name in (manifest.denied_tools or []):
        raise ToolDenied(f"tool '{tool_name}' denied by stage '{manifest.id}'")
    if manifest.allowed_tools and tool_name not in manifest.allowed_tools:
        raise ToolDenied(f"tool '{tool_name}' not in stage '{manifest.id}' allowlist")


def classify_failure(error_class: str, policy: RetryPolicy, attempt: int) -> str:
    """Return 'retry' or 'abort'. Explicit deny wins over allow."""
    if error_class in (policy.no_retry_on or []):
        return "abort"
    if attempt >= policy.max_attempts:
        return "abort"
    if error_class in (policy.retry_on or []):
        return "retry"
    return "abort"


def idempotency_key(stage_id: str, task_id: str, action: str) -> str:
    raw = f"{stage_id}\x00{task_id}\x00{action}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def side_effect_already_applied(applied_keys: set[str], key: str) -> bool:
    return key in applied_keys
