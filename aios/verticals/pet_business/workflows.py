"""ICM-X contracts for the workflows this vertical actually sells.

These are the paid workflow classes: an agent that declares one of them in
``extra_data["workflow_class"]`` cannot run without the matching contract
(``aios.icm.agent_binding.assert_paid_workflow_contract``). Opt-in ICM-X stays
available for experiments and internal utilities.
"""

from __future__ import annotations

from aios.icm.contracts import ContextPolicy, RetryPolicy, StageManifest

# ─── lead capture: inbound enquiry -> qualified lead or escalation ───
LEAD_CAPTURE = StageManifest(
    id="pet_lead_capture",
    version="1.0.0",
    description=(
        "Answer an inbound WhatsApp enquiry from the approved business profile, "
        "qualify the customer and hand off to a human when the request is "
        "outside the profile or clinically sensitive."
    ),
    mode="llm",
    timeout_seconds=90,
    max_llm_calls=4,
    max_cost_usd=0.10,
    inputs_schema="pet.enquiry.v1",
    outputs_schema="pet.qualified_lead.v1",
    context=ContextPolicy(
        layers=["identity", "stage", "static_references"],
        max_context_tokens=6_000,
    ),
    allowed_tools=["rag_search", "crm_create_deal", "cal_booking", "notify_human"],
    denied_tools=["execute_code", "python_sandbox", "sql_query"],
    side_effects=True,
    approval_required=False,
    retry=RetryPolicy(max_attempts=2),
)

# ─── follow-up: recover an unanswered/abandoned conversation ───
LEAD_FOLLOW_UP = StageManifest(
    id="pet_lead_follow_up",
    version="1.0.0",
    description=(
        "Send a bounded follow-up only when the customer has not opted out, "
        "the follow-up cap and minimum interval are respected, and the message "
        "quotes approved information."
    ),
    mode="llm",
    timeout_seconds=60,
    max_llm_calls=2,
    max_cost_usd=0.05,
    inputs_schema="pet.lead_context.v1",
    outputs_schema="pet.follow_up_result.v1",
    context=ContextPolicy(
        layers=["identity", "stage", "dynamic_references"],
        max_context_tokens=4_000,
    ),
    allowed_tools=["send_whatsapp", "crm_update_deal", "notify_human"],
    denied_tools=["execute_code", "python_sandbox", "sql_query", "make_voice_call"],
    side_effects=True,
    approval_required=True,
    retry=RetryPolicy(max_attempts=1, retry_on=["timeout"]),
)

# Workflow class name -> contract. The name is what an agent declares; the
# contract is what the runtime enforces.
WORKFLOW_CONTRACTS: dict[str, StageManifest] = {
    "pet_lead_capture": LEAD_CAPTURE,
    "pet_lead_follow_up": LEAD_FOLLOW_UP,
}


class UnknownPaidWorkflow(KeyError):
    """Declared a paid workflow class that has no contract owned by any vertical."""


def contract_for(workflow_class: str) -> StageManifest:
    try:
        return WORKFLOW_CONTRACTS[workflow_class]
    except KeyError as exc:
        raise UnknownPaidWorkflow(workflow_class) from exc


def paid_workflow_class(extra_data: dict | None) -> str | None:
    """The workflow class an agent declares, or ``None`` for internal agents."""
    if not isinstance(extra_data, dict):
        return None
    value = extra_data.get("workflow_class")
    return value if isinstance(value, str) and value else None


def has_contract(workflow_class: str | None) -> bool:
    return bool(workflow_class) and workflow_class in WORKFLOW_CONTRACTS
