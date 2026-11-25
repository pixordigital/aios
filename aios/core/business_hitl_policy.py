"""Human-in-the-loop policy for business side effects.

Human owner remains accountable; HITL required for side-effectful/external commitments.
Fail-closed: unknown categories require human approval.
"""

from __future__ import annotations

from enum import Enum


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


def requires_human_approval(
    action_category: SideEffectCategory | str,
    configured: bool = False,
) -> bool:
    """Return whether an action category requires human approval.

    Money, external commitment, legal, data deletion, and bulk send always
    require HITL. Read-only actions do not. Unknown categories fail closed and
    require HITL regardless of `configured`.
    """
    category = _coerce_category(action_category)
    if category in HITL_NOT_REQUIRED_CATEGORIES:
        return False
    if category in HITL_REQUIRED_CATEGORIES:
        return True
    # Fail closed for unknown/missing categories.
    return True


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
