"""US car dealership vertical: profile, policies, workflow contracts and metrics.

Scope: capture inquiries, answer from approved business data, qualify leads,
recover abandoned conversations, support repeat/return shoppers and hand
exceptions to staff. No legal/credit guarantees; pricing/financing must come
from approved profile or be escalated.
"""

from .metrics import OutcomeCounts, summarize_outcomes
from .policies import FollowUpDecision, may_follow_up, requires_human
from .profile import CarDealershipUSProfile, ServiceItem
from .workflows import (
    WORKFLOW_CONTRACTS,
    contract_for,
    has_contract,
    paid_workflow_class,
)

__all__ = [
    "CarDealershipUSProfile",
    "ServiceItem",
    "WORKFLOW_CONTRACTS",
    "contract_for",
    "has_contract",
    "paid_workflow_class",
    "FollowUpDecision",
    "may_follow_up",
    "requires_human",
    "OutcomeCounts",
    "summarize_outcomes",
]
