"""Central action policy for tool execution.

Governance-encoded, fail-closed. Evaluated before tool execution as defense-in-depth.
Unknown side-effecting tools default to approval required in production-sensitive paths.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ActionClass(str, Enum):
    READ_INTERNAL = "read_internal"
    REVERSIBLE_INTERNAL = "reversible_internal"
    MONEY = "money"
    EXTERNAL_COMMITMENT = "external_commitment"
    PII_LEGAL = "pii_legal"
    BULK_COMMS = "bulk_comms"
    DESTRUCTIVE = "destructive"
    PROD_PUBLISH = "prod_publish"
    ROUTINE_SIDE_EFFECT = "routine_side_effect"
    UNKNOWN_SIDE_EFFECT = "unknown_side_effect"


# Classes that always require human approval / HITL.
APPROVAL_REQUIRED_CLASSES: frozenset[ActionClass] = frozenset(
    {
        ActionClass.MONEY,
        ActionClass.PII_LEGAL,
        ActionClass.BULK_COMMS,
        ActionClass.DESTRUCTIVE,
        ActionClass.PROD_PUBLISH,
        ActionClass.ROUTINE_SIDE_EFFECT,
        ActionClass.UNKNOWN_SIDE_EFFECT,
    }
)

# External commitments: approval required in production-sensitive contexts; otherwise
# agent HITL/autonomy governs.
PRODUCTION_SENSITIVE_APPROVAL_CLASSES: frozenset[ActionClass] = frozenset(
    {ActionClass.EXTERNAL_COMMITMENT}
)

# Classes allowed without HITL by default (still subject to normal auth/governance).
APPROVAL_FREE_CLASSES: frozenset[ActionClass] = frozenset(
    {ActionClass.READ_INTERNAL, ActionClass.REVERSIBLE_INTERNAL}
)

# Known tool classifications. Unknown tools fail closed as UNKNOWN_SIDE_EFFECT unless
# explicitly marked read-only by safe allowlist.
TOOL_ACTION_CLASSES: dict[str, ActionClass] = {
    # read/internal
    "calculator": ActionClass.READ_INTERNAL,
    "current_datetime": ActionClass.READ_INTERNAL,
    "read_file": ActionClass.READ_INTERNAL,
    "web_search": ActionClass.READ_INTERNAL,
    "http_get": ActionClass.READ_INTERNAL,
    "rag_search": ActionClass.READ_INTERNAL,
    "hybrid_search": ActionClass.READ_INTERNAL,
    "knowledge_search": ActionClass.READ_INTERNAL,
    "crm_list_deals": ActionClass.READ_INTERNAL,
    "crm_stale_deals": ActionClass.READ_INTERNAL,
    "crm_pipeline_stats": ActionClass.READ_INTERNAL,
    "lead_list": ActionClass.READ_INTERNAL,
    "lead_score": ActionClass.READ_INTERNAL,
    "calendar_check_availability": ActionClass.READ_INTERNAL,
    "calendar_list_events": ActionClass.READ_INTERNAL,
    "whatsapp_template_list": ActionClass.READ_INTERNAL,
    "whatsapp_template_lint": ActionClass.READ_INTERNAL,
    "proactive_alerts": ActionClass.READ_INTERNAL,
    "transcribe": ActionClass.READ_INTERNAL,
    "load_project_skills": ActionClass.READ_INTERNAL,
    "read_skill": ActionClass.READ_INTERNAL,
    "memory": ActionClass.READ_INTERNAL,
    "ask_team_manager": ActionClass.READ_INTERNAL,
    # reversible/internal drafts or low-risk internal writes
    "lead_save": ActionClass.REVERSIBLE_INTERNAL,
    "lead_review": ActionClass.REVERSIBLE_INTERNAL,
    "crm_set_follow_up": ActionClass.REVERSIBLE_INTERNAL,
    "code": ActionClass.REVERSIBLE_INTERNAL,
    "transform": ActionClass.REVERSIBLE_INTERNAL,
    "if_branch": ActionClass.REVERSIBLE_INTERNAL,
    "wait": ActionClass.REVERSIBLE_INTERNAL,
    "whatsapp_template_draft": ActionClass.REVERSIBLE_INTERNAL,
    # money
    "crm_update_deal": ActionClass.MONEY,  # refined by args
    "crm_create_deal": ActionClass.MONEY,  # may carry value; refined by args
    # external commitment / comms
    "send_email": ActionClass.EXTERNAL_COMMITMENT,
    "http_request": ActionClass.EXTERNAL_COMMITMENT,
    "notify_human": ActionClass.EXTERNAL_COMMITMENT,
    "whatsapp_template": ActionClass.EXTERNAL_COMMITMENT,
    "voice_call": ActionClass.EXTERNAL_COMMITMENT,
    "calendar_create_event": ActionClass.EXTERNAL_COMMITMENT,
    "cal_booking": ActionClass.EXTERNAL_COMMITMENT,
    "hubspot": ActionClass.EXTERNAL_COMMITMENT,
    "pipedrive": ActionClass.EXTERNAL_COMMITMENT,
    "rdstation": ActionClass.EXTERNAL_COMMITMENT,
    "request_build": ActionClass.EXTERNAL_COMMITMENT,
    # destructive
    "crm_delete_deal": ActionClass.DESTRUCTIVE,
    "crm_merge_deals": ActionClass.DESTRUCTIVE,
    "sql_query": ActionClass.READ_INTERNAL,  # refined by args; destructive payload => destructive
    "python_sandbox": ActionClass.REVERSIBLE_INTERNAL,  # refined by args
    # routine/prod
    "routine_side_effect_approve": ActionClass.ROUTINE_SIDE_EFFECT,
}

# Tools known to be read-only regardless of unknown registry drift.
SAFE_READ_ONLY_TOOLS: frozenset[str] = frozenset(
    name for name, cls in TOOL_ACTION_CLASSES.items() if cls == ActionClass.READ_INTERNAL
)


@dataclass(frozen=True)
class ActionDecision:
    tool_name: str
    action_class: ActionClass
    requires_approval: bool
    reason: str = ""
    fail_closed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "action_class": self.action_class.value,
            "requires_approval": self.requires_approval,
            "reason": self.reason,
            "fail_closed": self.fail_closed,
        }


def _parse_args(fn_args: Any) -> dict[str, Any]:
    if isinstance(fn_args, dict):
        return fn_args
    if isinstance(fn_args, str):
        try:
            parsed = json.loads(fn_args)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _has_destructive_payload(args: dict[str, Any]) -> bool:
    destructive = ("DELETE ", "DROP ", "TRUNCATE ", "ALTER ", "PG_")
    payload = " ".join(str(args.get(k, "")) for k in ("code", "sql", "query", "script", "command")).upper()
    if any(word in payload for word in destructive):
        return True
    # broad payload scan for known risky tools
    raw = str(args).upper()
    return any(word in raw for word in destructive)


def _bulk_recipient_count(args: dict[str, Any]) -> int:
    for key in ("to", "to_emails", "recipients", "emails"):
        v = args.get(key)
        if isinstance(v, (list, tuple, set)):
            return len(v)
    return 0


def classify_tool_action(tool_name: str, fn_args: Any = None, *, context: dict[str, Any] | None = None) -> ActionDecision:
    """Classify tool call into action class. Fail-closed for unknown side effects."""
    ctx = context or {}
    args = _parse_args(fn_args)
    name = str(tool_name or "").strip()
    if not name:
        return ActionDecision(name, ActionClass.UNKNOWN_SIDE_EFFECT, True, "missing tool name", fail_closed=True)

    # Dynamic tools: untrusted arbitrary code/effects.
    try:
        from aios.tools.registry import TOOL_REGISTRY

        entry = TOOL_REGISTRY.get(name)
        if isinstance(entry, dict) and entry.get("dynamic") is True:
            return ActionDecision(name, ActionClass.UNKNOWN_SIDE_EFFECT, True, f"dynamic tool '{name}' requires approval", fail_closed=True)
    except Exception:
        logger.debug("action_policy registry lookup failed for %s", name, exc_info=True)

    base = TOOL_ACTION_CLASSES.get(name)

    # Arg-sensitive refinements
    if name == "send_email":
        count = _bulk_recipient_count(args)
        threshold = int(ctx.get("bulk_email_threshold", 100) or 100)
        if count >= threshold:
            return ActionDecision(name, ActionClass.BULK_COMMS, True, f"bulk email to {count} recipients requires approval")
        return ActionDecision(name, ActionClass.EXTERNAL_COMMITMENT, True, "external email requires approval")

    if name == "crm_update_deal":
        stage = str(args.get("stage", "")).lower()
        if stage in {"closed_won", "closed_lost"}:
            return ActionDecision(name, ActionClass.MONEY, True, f"closing deal at {stage} requires approval")
        money_keys = ("value", "amount", "valor")
        value_threshold = float(ctx.get("hitl_value_threshold", 5000) or 0)
        for k in money_keys:
            v = args.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and value_threshold and v >= value_threshold:
                return ActionDecision(name, ActionClass.MONEY, True, f"{k}={v} at or above HITL ceiling {value_threshold}")
        discount_threshold = float(ctx.get("hitl_discount_threshold", 10) or 0)
        for k in ("discount", "desconto"):
            v = args.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and discount_threshold and v >= discount_threshold:
                return ActionDecision(name, ActionClass.MONEY, True, f"{k}={v}% at or above HITL ceiling {discount_threshold}%")
        # regular update is reversible/internal, but keep compatible with existing behavior? existing only gated close/value/discount.
        return ActionDecision(name, ActionClass.REVERSIBLE_INTERNAL, False, "")

    if name == "crm_create_deal":
        value_threshold = float(ctx.get("hitl_value_threshold", 5000) or 0)
        for k in ("value", "amount", "valor"):
            v = args.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and value_threshold and v >= value_threshold:
                return ActionDecision(name, ActionClass.MONEY, True, f"{k}={v} at or above HITL ceiling {value_threshold}")
        return ActionDecision(name, ActionClass.EXTERNAL_COMMITMENT, True, "crm deal creation may trigger external side effects; approval required")

    if name in {"sql_query", "python_sandbox", "code"}:
        if _has_destructive_payload(args):
            return ActionDecision(name, ActionClass.DESTRUCTIVE, True, f"destructive {name} call requires approval")
        if base == ActionClass.READ_INTERNAL:
            return ActionDecision(name, base, False, "")
        return ActionDecision(name, ActionClass.REVERSIBLE_INTERNAL, False, "")

    if name == "http_request":
        # External by default; prod publish heuristic
        url = str(args.get("url", "")).lower()
        method = str(args.get("method", "GET")).upper()
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            if any(s in url for s in ("deploy", "publish", "release", "prod", "production")):
                return ActionDecision(name, ActionClass.PROD_PUBLISH, True, "production publish/deploy request requires approval")
            return ActionDecision(name, ActionClass.EXTERNAL_COMMITMENT, True, "external mutating HTTP request requires approval")
        return ActionDecision(name, ActionClass.READ_INTERNAL, False, "")

    if base is not None:
        requires = base in APPROVAL_REQUIRED_CLASSES or base in PRODUCTION_SENSITIVE_APPROVAL_CLASSES
        if requires:
            if base == ActionClass.DESTRUCTIVE:
                reason = f"destructive tool '{name}' requires approval"
            elif base == ActionClass.EXTERNAL_COMMITMENT:
                reason = f"external commitment tool '{name}' requires approval"
            elif base == ActionClass.MONEY:
                reason = f"money/financial action '{name}' requires approval"
            else:
                reason = f"{base.value} action requires approval"
        else:
            reason = ""
        return ActionDecision(name, base, requires, reason)

    # Unknown tool: fail closed. If explicitly configured as safe read-only in context, allow.
    safe_reads = set(ctx.get("safe_read_tools") or [])
    if name in safe_reads:
        return ActionDecision(name, ActionClass.READ_INTERNAL, False, "")
    return ActionDecision(
        name,
        ActionClass.UNKNOWN_SIDE_EFFECT,
        True,
        f"unknown side-effecting tool '{name}' requires approval (fail-closed)",
        fail_closed=True,
    )


def requires_human_approval(tool_name: str, fn_args: Any = None, *, context: dict[str, Any] | None = None) -> bool:
    return classify_tool_action(tool_name, fn_args, context=context).requires_approval


__all__ = [
    "ActionClass",
    "ActionDecision",
    "APPROVAL_REQUIRED_CLASSES",
    "APPROVAL_FREE_CLASSES",
    "TOOL_ACTION_CLASSES",
    "classify_tool_action",
    "requires_human_approval",
]