"""ICM-X contracts for US car dealership paid workflows.

Agents declaring these workflow_class values must bind to the matching
contract (enforced by aios.icm.agent_binding). Opt-in ICM-X remains available
for experiments/internal agents.
"""

from __future__ import annotations

from aios.icm.contracts import ContextPolicy, RetryPolicy, StageManifest

# ─── lead capture: inbound inquiry -> qualified lead or escalation ───
LEAD_CAPTURE = StageManifest(
    id="car_dealership_us_lead_capture",
    version="1.0.0",
    description=(
        "Answer an inbound inquiry (web/phone/text relay) from approved "
        "dealership profile, qualify the shopper (vehicle interest, timeline, "
        "trade-in), and hand off when outside profile, financing/legal sensitive, "
        "or pricing not approved."
    ),
    mode="llm",
    timeout_seconds=90,
    max_llm_calls=4,
    max_cost_usd=0.10,
    inputs_schema="cdus.enquiry.v1",
    outputs_schema="cdus.qualified_lead.v1",
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

# ─── follow-up: recover unanswered/abandoned conversation ───
LEAD_FOLLOW_UP = StageManifest(
    id="car_dealership_us_lead_follow_up",
    version="1.0.0",
    description=(
        "Send a bounded follow-up only if customer not opted out, cadence/cap "
        "respected, and message quotes approved info only (no made-up pricing)."
    ),
    mode="llm",
    timeout_seconds=60,
    max_llm_calls=2,
    max_cost_usd=0.05,
    inputs_schema="cdus.lead_context.v1",
    outputs_schema="cdus.follow_up_result.v1",
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

WORKFLOW_CONTRACTS: dict[str, StageManifest] = {
    "car_dealership_us_lead_capture": LEAD_CAPTURE,
    "car_dealership_us_lead_follow_up": LEAD_FOLLOW_UP,
}


class UnknownPaidWorkflow(KeyError):
    """Declared paid workflow class has no contract in this vertical."""


def contract_for(workflow_class: str) -> StageManifest:
    try:
        return WORKFLOW_CONTRACTS[workflow_class]
    except KeyError as exc:
        raise UnknownPaidWorkflow(workflow_class) from exc


def paid_workflow_class(extra_data: dict | None) -> str | None:
    if not isinstance(extra_data, dict):
        return None
    value = extra_data.get("workflow_class")
    return value if isinstance(value, str) and value else None


def has_contract(workflow_class: str | None) -> bool:
    return bool(workflow_class) and workflow_class in WORKFLOW_CONTRACTS
