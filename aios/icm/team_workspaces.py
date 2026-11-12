"""Versioned ICM-X workspaces and stage contracts for the AIOS teams.

Each workspace holds the three context layers the adapter knows how to load
(identity, routing, stage) plus one manifest per agent role. Seeding is
idempotent: rerunning rewrites the same files, so a stage contract is changed
by editing this module and re-running the provisioner, never by hand on a
server.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from aios.icm.workspace import WorkspacePaths

_CONTEXT_LAYERS = ["identity", "routing", "stage", "static_references"]

# agent name -> (workspace, stage)
AGENT_STAGES: dict[str, tuple[str, str]] = {
    "sales-sdr": ("sales_ops", "sdr_prospecting"),
    "sales-closer": ("sales_ops", "closer_deal_execution"),
    "sales-manager": ("sales_ops", "sales_review"),
    "dev-frontend": ("dev_ops", "frontend_delivery"),
    "dev-backend": ("dev_ops", "backend_delivery"),
    "dev-manager": ("dev_ops", "dev_review"),
    "red-agent": ("red_ops", "offensive_test"),
    "red-manager": ("red_ops", "red_review"),
    "blue-agent": ("blue_ops", "detection_analysis"),
    "blue-manager": ("blue_ops", "blue_review"),
    "Data Analyst": ("data_ops", "data_analysis"),
    "Data Scientist": ("data_ops", "data_science"),
    "data-manager": ("data_ops", "data_review"),
}

# Only events with a real producer today. Agents with no entry stay
# request-driven on purpose; inventing subscriptions would make them wake for
# events nobody publishes.
AGENT_EVENTS: dict[str, list[str]] = {
    "sales-sdr": ["message.received", "crm.stage_changed.new"],
    "sales-closer": ["crm.stage_changed.qualified", "crm.deal_stalled", "sales.drop_detected"],
    "sales-manager": [
        "crm.stage_changed.won",
        "crm.stage_changed.lost",
        "crm.deal_stalled",
        "sales.drop_detected",
    ],
    "dev-manager": ["agent.verify_failed", "agent.deploy_failed"],
    "red-agent": ["agent.verify_failed"],
    "red-manager": ["agent.verify_failed", "agent.deploy_failed"],
    "blue-agent": ["agent.deploy_failed"],
    "blue-manager": ["agent.verify_failed", "agent.deploy_failed"],
}


def _stage(
    description: str,
    context_md: str,
    allowed_tools: list[str],
    denied_tools: list[str] | None = None,
    *,
    timeout_seconds: int = 180,
    max_llm_calls: int = 8,
    max_cost_usd: float = 0.5,
    side_effects: bool = False,
) -> dict:
    return {
        "description": description,
        "context_md": context_md,
        "allowed_tools": allowed_tools,
        "denied_tools": denied_tools or [],
        "timeout_seconds": timeout_seconds,
        "max_llm_calls": max_llm_calls,
        "max_cost_usd": max_cost_usd,
        "side_effects": side_effects,
    }


TEAM_WORKSPACES: dict[str, dict] = {
    "sales_ops": {
        "identity": (
            "# Sales Operations Workspace\n\n"
            "- ID: `sales_ops`\n- Version: `1.0.0`\n"
            "- Purpose: qualify inbound and outbound leads, move deals through the "
            "pipeline, and keep follow-ups from going stale.\n"
            "- Authority: CRM records are the source of truth; only CRM tools may "
            "change deal state.\n"
        ),
        "routes": (
            "# Routing Policies\n\n"
            "- New inbound message or lead -> `sdr_prospecting`.\n"
            "- Qualified/won/lost deal, stalled deal, drop detected -> `closer_deal_execution`.\n"
            "- Pipeline review and escalations -> `sales_review`.\n"
            "- Prohibited: inventing prices, discounts, or deal values without the calculator tool.\n"
        ),
        "stages": {
            "sdr_prospecting": _stage(
                "Qualify inbound and outbound leads before handoff to a closer",
                "# Stage Instructions: SDR Prospecting\n\n"
                "1. Score the lead with `lead_score` before any outreach.\n"
                "2. Research the company with `web_search` / `rag_search`; never invent facts.\n"
                "3. Create or update the CRM record and set the next follow-up.\n"
                "4. Hand off only qualified leads; explain the score and the buying signal.\n"
                "5. Do not merge deals or promise pricing.\n",
                ["lead_score", "web_search", "rag_search", "crm_create_deal",
                 "crm_list_deals", "crm_update_deal", "crm_set_follow_up",
                 "send_email", "current_datetime", "http_request"],
                ["crm_merge_deals", "crm_stale_deals"],
                max_cost_usd=0.35,
            ),
            "closer_deal_execution": _stage(
                "Run an active deal: follow-ups, stage moves, and customer replies",
                "# Stage Instructions: Deal Execution\n\n"
                "1. Read the deal and its history before replying.\n"
                "2. Any value or discount must be computed, not guessed.\n"
                "3. Update the stage only on a real change and set the next follow-up.\n"
                "4. Destructive or merge operations require human approval.\n",
                ["calculator", "crm_list_deals", "crm_update_deal", "crm_set_follow_up",
                 "crm_stale_deals", "send_email", "rag_search", "current_datetime",
                 "http_request"],
                ["crm_merge_deals", "crm_create_deal"],
                max_cost_usd=0.6,
                side_effects=True,
            ),
            "sales_review": _stage(
                "Review pipeline health, stalled deals, and team escalations",
                "# Stage Instructions: Sales Review\n\n"
                "1. Read the pipeline and stalled deals; do not modify deals in a review.\n"
                "2. Rank risks by value and age, and name the owner of each next action.\n"
                "3. Escalate blockers with `notify_human`; do not silently accept them.\n",
                ["crm_list_deals", "crm_stale_deals", "lead_score", "calculator",
                 "rag_search", "current_datetime", "ask_team_manager", "notify_human"],
                ["crm_create_deal", "crm_update_deal", "crm_merge_deals"],
                side_effects=False,
            ),
        },
    },
    "dev_ops": {
        "identity": (
            "# Engineering Workspace\n\n"
            "- ID: `dev_ops`\n- Version: `1.0.0`\n"
            "- Purpose: deliver and review code changes without breaking production.\n"
            "- Authority: source files are read-only in review stages; delivery stages "
            "may run code only in the sandbox.\n"
        ),
        "routes": (
            "# Routing Policies\n\n"
            "- UI work -> `frontend_delivery`.\n"
            "- Data/API work -> `backend_delivery`.\n"
            "- Deploy or verification failure -> `dev_review`.\n"
            "- Prohibited: destructive shell or database operations without approval.\n"
        ),
        "stages": {
            "frontend_delivery": _stage(
                "Implement and verify frontend changes",
                "# Stage Instructions: Frontend Delivery\n\n"
                "1. Read the existing component before changing it.\n"
                "2. Keep the change minimal and consistent with the current patterns.\n"
                "3. Verify with the sandbox or HTTP request; report what was actually run.\n",
                ["read_file", "code", "python_sandbox", "http_request", "web_search",
                 "rag_search", "current_datetime"],
                ["sql_query"],
                max_cost_usd=0.7,
            ),
            "backend_delivery": _stage(
                "Implement and verify backend changes",
                "# Stage Instructions: Backend Delivery\n\n"
                "1. Read the code and schema before editing.\n"
                "2. Use read-only `sql_query` for inspection; never mutate production data.\n"
                "3. Verify with the sandbox and report the exact command and result.\n",
                ["read_file", "code", "sql_query", "python_sandbox", "http_request",
                 "web_search", "rag_search", "current_datetime"],
                [],
                max_cost_usd=0.7,
            ),
            "dev_review": _stage(
                "Review a change, a failure, or a deploy result",
                "# Stage Instructions: Engineering Review\n\n"
                "1. Identify the failing behavior and the smallest root cause.\n"
                "2. Do not edit code in a review; report the fix and the file path.\n"
                "3. Escalate production-impacting failures with `notify_human`.\n",
                ["read_file", "web_search", "rag_search", "current_datetime",
                 "ask_team_manager", "notify_human"],
                ["code", "sql_query", "python_sandbox"],
            ),
        },
    },
    "red_ops": {
        "identity": (
            "# Red Team Workspace\n\n"
            "- ID: `red_ops`\n- Version: `1.0.0`\n"
            "- Purpose: find exploitable weaknesses before customers do.\n"
            "- Authority: test only systems the org owns; never attack third parties.\n"
        ),
        "routes": (
            "# Routing Policies\n\n"
            "- New target or hypothesis -> `offensive_test`.\n"
            "- Findings, risk ranking, and remediation -> `red_review`.\n"
            "- Prohibited: exfiltrating real customer data or leaving backdoors.\n"
        ),
        "stages": {
            "offensive_test": _stage(
                "Test an owned surface for a specific weakness",
                "# Stage Instructions: Offensive Test\n\n"
                "1. State the hypothesis and the owned target before testing.\n"
                "2. Use the least intrusive technique that proves or disproves it.\n"
                "3. Record evidence (request/response) without storing personal data.\n"
                "4. Stop on any sign of data exfiltration or service degradation.\n",
                ["read_file", "web_search", "http_request", "python_sandbox",
                 "sql_query", "current_datetime"],
                [],
                max_cost_usd=0.8,
                side_effects=True,
            ),
            "red_review": _stage(
                "Rank findings and write remediation guidance",
                "# Stage Instructions: Red Review\n\n"
                "1. Rank findings by exploitability and business impact.\n"
                "2. Give one concrete remediation per finding with the affected surface.\n"
                "3. Do not run new attacks in a review stage.\n",
                ["read_file", "web_search", "rag_search", "current_datetime",
                 "ask_team_manager", "notify_human"],
                ["http_request", "python_sandbox", "sql_query"],
            ),
        },
    },
    "blue_ops": {
        "identity": (
            "# Blue Team Workspace\n\n"
            "- ID: `blue_ops`\n- Version: `1.0.0`\n"
            "- Purpose: detect, contain, and explain security and reliability incidents.\n"
            "- Authority: read production telemetry; containment actions need approval.\n"
        ),
        "routes": (
            "# Routing Policies\n\n"
            "- New alert or anomaly -> `detection_analysis`.\n"
            "- Confirmed incident and postmortem -> `blue_review`.\n"
            "- Prohibited: deleting logs or disabling monitoring to make an alert go away.\n"
        ),
        "stages": {
            "detection_analysis": _stage(
                "Analyze an alert or anomaly and decide whether it is an incident",
                "# Stage Instructions: Detection Analysis\n\n"
                "1. Correlate logs, metrics, and recent deploys before concluding.\n"
                "2. Separate evidence from hypothesis; cite the source of each fact.\n"
                "3. Classify severity and name the smallest safe containment.\n",
                ["read_file", "code", "sql_query", "python_sandbox", "http_request",
                 "web_search", "rag_search", "current_datetime"],
                [],
                max_cost_usd=0.8,
            ),
            "blue_review": _stage(
                "Write the incident timeline, root cause, and prevention plan",
                "# Stage Instructions: Incident Review\n\n"
                "1. Build a timestamped timeline from observed evidence only.\n"
                "2. State root cause, blast radius, and detection gap.\n"
                "3. One preventive action with an owner and a due date.\n"
                "4. Do not run containment actions in a review stage.\n",
                ["read_file", "web_search", "rag_search", "current_datetime",
                 "ask_team_manager", "notify_human"],
                ["python_sandbox", "sql_query"],
            ),
        },
    },
    "data_ops": {
        "identity": (
            "# Data Workspace\n\n"
            "- ID: `data_ops`\n- Version: `1.0.0`\n"
            "- Purpose: answer business questions with reproducible analysis.\n"
            "- Authority: analysis is read-only; no production writes.\n"
        ),
        "routes": (
            "# Routing Policies\n\n"
            "- Recurring business question -> `data_analysis`.\n"
            "- Statistical or modeling question -> `data_science`.\n"
            "- Review of a deliverable or a disputed number -> `data_review`.\n"
            "- Prohibited: presenting an estimate as a measured number.\n"
        ),
        "stages": {
            "data_analysis": _stage(
                "Answer a business question from SQL and reproducible calculations",
                "# Stage Instructions: Data Analysis\n\n"
                "1. State the question and the exact query used.\n"
                "2. Show row counts and the time window; call out missing data.\n"
                "3. Label estimates as estimates, never as measurements.\n",
                ["sql_query", "python_sandbox", "calculator", "read_file",
                 "rag_search", "web_search", "current_datetime"],
                [],
                max_cost_usd=0.6,
            ),
            "data_science": _stage(
                "Run a statistical or modeling analysis with stated assumptions",
                "# Stage Instructions: Data Science\n\n"
                "1. State assumptions and the validation method before results.\n"
                "2. Report effect size and uncertainty, not just a point estimate.\n"
                "3. Keep the analysis reproducible in the sandbox.\n",
                ["sql_query", "python_sandbox", "calculator", "read_file",
                 "rag_search", "web_search", "current_datetime"],
                [],
                max_cost_usd=0.9,
            ),
            "data_review": _stage(
                "Check a deliverable's numbers, sources, and claims",
                "# Stage Instructions: Data Review\n\n"
                "1. Re-derive the headline number from its stated source.\n"
                "2. Flag any estimate presented as fact or any missing time window.\n"
                "3. Do not publish a number that cannot be reproduced.\n",
                ["sql_query", "read_file", "calculator", "rag_search",
                 "current_datetime", "ask_team_manager", "notify_human"],
                ["python_sandbox"],
            ),
        },
    },
}


def seed_team_workspaces(
    storage_root: str | Path,
    org_id: str,
    workspaces: list[str] | None = None,
) -> list[Path]:
    """Write the team workspaces under the org's tenant directory."""
    paths = WorkspacePaths(Path(storage_root))
    written: list[Path] = []
    for workspace_id, workspace in TEAM_WORKSPACES.items():
        if workspaces and workspace_id not in workspaces:
            continue
        ws_dir = paths.ensure_workspace_scaffold(org_id, workspace_id)
        (ws_dir / "L0" / "WORKSPACE.md").write_text(workspace["identity"], encoding="utf-8")
        (ws_dir / "L1" / "ROUTES.md").write_text(workspace["routes"], encoding="utf-8")
        for stage_id, stage in workspace["stages"].items():
            stage_dir = paths.stage(org_id, workspace_id, stage_id)
            stage_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "id": stage_id,
                "version": "1.0.0",
                "description": stage["description"],
                "mode": "llm",
                "timeout_seconds": stage["timeout_seconds"],
                "max_llm_calls": stage["max_llm_calls"],
                "max_cost_usd": stage["max_cost_usd"],
                "context": {"layers": _CONTEXT_LAYERS, "max_context_tokens": 6000},
                "allowed_tools": stage["allowed_tools"],
                "denied_tools": stage["denied_tools"],
                "side_effects": stage["side_effects"],
                "approval_required": False,
            }
            (stage_dir / "stage.yaml").write_text(
                yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
            )
            (stage_dir / "CONTEXT.md").write_text(stage["context_md"], encoding="utf-8")
        written.append(ws_dir)
    return written
