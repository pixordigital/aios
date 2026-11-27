"""Human-in-the-loop policy for business side effects.

Human owner remains accountable; HITL required for side-effectful/external commitments.
Fail-closed: unknown categories require human approval.
"""

from __future__ import annotations

from enum import Enum

from aios.core.action_policy import ActionClass, classify_tool_action


class SideEffectCategory(str, Enum):
    """Categories of business actions for HITL policy decisions."""

    MONEY = "money"
    EXTERNAL_COMMITMENT = "external_commitment"
    LEGAL = "legal"
    DATA_DELETE = "data_delete"
    BULK_SEND = "bulk_send"
    READ_ONLY = "read_only"


# Side-effect categories that always require human approval.
HITL_REQUIRED_CATEGORIES: frozenset[SideEffectCategory] = frozenset(
    {
        SideEffectCategory.MONEY,
        SideEffectCategory.EXTERNAL_COMMITMENT,
        SideEffectCategory.LEGAL,
        SideEffectCategory.DATA_DELETE,
        SideEffectCategory.BULK_SEND,
    }
)

# Explicit non-HITL categories. Unknown categories fail closed (require HITL).
HITL_NOT_REQUIRED_CATEGORIES: frozenset[SideEffectCategory] = frozenset(
    {SideEffectCategory.READ_ONLY}
)


def _coerce_category(
    action_category: SideEffectCategory | str,
) -> SideEffectCategory | None:
    if isinstance(action_category, SideEffectCategory):
        return action_category
    if isinstance(action_category, str):
        normalized = action_category.strip().lower()
        try:
            return SideEffectCategory(normalized)
        except ValueError:
            return None
    return None


# Compatibility map: legacy business categories -> central action classes.
_CATEGORY_TO_ACTION_CLASS = {
    SideEffectCategory.MONEY: ActionClass.MONEY,
    SideEffectCategory.EXTERNAL_COMMITMENT: ActionClass.EXTERNAL_COMMITMENT,
    SideEffectCategory.LEGAL: ActionClass.PII_LEGAL,
    SideEffectCategory.DATA_DELETE: ActionClass.DESTRUCTIVE,
    SideEffectCategory.BULK_SEND: ActionClass.BULK_COMMS,
    SideEffectCategory.READ_ONLY: ActionClass.READ_INTERNAL,
}


def requires_human_approval(
    action_category: SideEffectCategory | str,
    configured: bool = False,
) -> bool:
    """Return whether an action category requires human approval.

    Delegates to central action policy taxonomy. Unknown categories fail closed.
    """
    category = _coerce_category(action_category)
    if category is None:
        return True
    action_class = _CATEGORY_TO_ACTION_CLASS.get(category)
    if action_class is None:
        return True
    if action_class == ActionClass.READ_INTERNAL:
        return False
    # Any non-read action class in this policy requires approval.
    decision = classify_tool_action(
        "__policy_probe__",
        {},
        context={"safe_read_tools": []},
    )
    # Use taxonomy rule directly; probe only ensures module import path is valid.
    _ = (configured, decision)
    return action_class in {
        ActionClass.MONEY,
        ActionClass.EXTERNAL_COMMITMENT,
        ActionClass.PII_LEGAL,
        ActionClass.BULK_COMMS,
        ActionClass.DESTRUCTIVE,
        ActionClass.PROD_PUBLISH,
        ActionClass.ROUTINE_SIDE_EFFECT,
        ActionClass.UNKNOWN_SIDE_EFFECT,
    }


def owner_accountability_notice() -> str:
    """Clear accountability notice for side-effectful business actions."""
    return (
        "Human owner remains accountable for this action. "
        "AI may assist, but side-effectful or external commitments require "
        "human review and approval before execution."
    )


__all__ = [
    "HITL_NOT_REQUIRED_CATEGORIES",
    "HITL_REQUIRED_CATEGORIES",
    "SideEffectCategory",
    "owner_accountability_notice",
    "requires_human_approval",
]
