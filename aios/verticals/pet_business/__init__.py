"""Pet business vertical: profile, policies, workflow contracts and metrics.

Scope is deliberately commercial, not clinical: capture enquiries, answer from
approved business data, qualify leads, recover abandoned conversations, support
repeat purchases and hand exceptions to staff. No diagnosis, triage or
emergency handling.
"""

from .metrics import OutcomeCounts, summarize_outcomes
from .policies import FollowUpDecision, may_follow_up, requires_human
from .profile import PetBusinessProfile, ServiceItem
from .workflows import WORKFLOW_CONTRACTS, contract_for, paid_workflow_class

__all__ = [
    "PetBusinessProfile",
    "ServiceItem",
    "WORKFLOW_CONTRACTS",
    "contract_for",
    "paid_workflow_class",
    "FollowUpDecision",
    "may_follow_up",
    "requires_human",
    "OutcomeCounts",
    "summarize_outcomes",
]
