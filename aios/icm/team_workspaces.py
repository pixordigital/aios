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
    "blue-agent": ("blue_ops", "detection_analysis"),
    "security-manager": ("security_ops", "security_review"),
    "Data Analyst": ("data_ops", "data_analysis"),
    "Data Scientist": ("data_ops", "data_science"),
    "data-manager": ("data_ops", "data_review"),
    # Media & Growth
    "Media Manager": ("media_ops", "media_review"),
    "Market Intelligence Researcher": ("media_ops", "market_research"),
    "Content Strategist": ("media_ops", "content_strategy"),
    "Content Producer": ("media_ops", "content_production"),
    # Marketing
    "Marketing": ("marketing_ops", "demand_generation"),
    "Manager Marketing": ("marketing_ops", "marketing_review"),
    # Customer Success
    "Customer Success": ("customer_success_ops", "renewal_follow_up"),
    "Manager Cs": ("customer_success_ops", "cs_review"),
    "Support": ("customer_success_ops", "support_reply"),
    # Revenue & Operations
    "Revops": ("revops_ops", "revenue_analysis"),
    "Manager Revops": ("revops_ops", "revops_review"),
    "Deal Auditor": ("revops_ops", "deal_audit"),
    "Evidence Compiler": ("revops_ops", "evidence_compile"),
    "Human Auditor Assistant": ("revops_ops", "human_audit_assist"),
    "Pricing Guardian": ("revops_ops", "pricing_guard"),
    "Performance Watcher": ("revops_ops", "performance_watch"),
}

# Only bus events with a real publisher (jobs.py / cron_scheduler.py / crm2.py).
# Agents with no entry stay request-driven. Audit action names such as
# agent.deploy_failed / agent.verify_failed are not bus events. The wildcard
# matches real crm2.STAGES via prefix matching (aios/core/events.py).
AGENT_EVENTS: dict[str, list[str]] = {
    "sales-sdr": ["message.received"],
    "sales-closer": [
        "crm.deal_stalled", "sales.drop_detected", "crm.stage_changed.*",
    ],
    "sales-manager": [
        "crm.deal_stalled", "sales.drop_detected", "crm.stage_changed.*",
    ],
    "Support": ["message.received"],
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


def _role_stage(
    title: str,
    description: str,
    allowed_tools: list[str],
    denied_tools: list[str] | None = None,
    **kwargs,
) -> dict:
    """Build a role stage without repeating the same context boilerplate."""
    return _stage(
        description,
        f"# Stage Instructions: {title}\n\n{description}\n"
        "Use only tools declared here; cite the real source for every claim or number.\n",
        allowed_tools,
        denied_tools,
        **kwargs,
    )


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
                 "send_email", "current_datetime", "http_request",
                 "cal_booking", "ask_team_manager", "notify_human", "calculator", "whatsapp_template"],
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
                 "http_request", "lead_score", "ask_team_manager", "notify_human",
                 "cal_booking", "web_search"],
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
                 "rag_search", "current_datetime", "ask_team_manager", "notify_human",
                 "crm_pipeline_stats", "cal_booking"],
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
                 "rag_search", "current_datetime", "ask_team_manager", "notify_human"],
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
                 "web_search", "rag_search", "current_datetime", "ask_team_manager",
                 "notify_human", "request_build"],
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
                 "ask_team_manager", "notify_human", "request_build"],
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
                 "sql_query", "current_datetime", "ask_team_manager", "notify_human", "rag_search"],
                [],
                max_cost_usd=0.8,
                side_effects=True,
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
                 "web_search", "rag_search", "current_datetime", "ask_team_manager", "notify_human"],
                [],
                max_cost_usd=0.8,
            ),
        },
    },
    "security_ops": {
        "identity": (
            "# Security Workspace\n\n"
            "- ID: `security_ops`\n- Version: `1.0.0`\n"
            "- Purpose: one lead for offensive findings and defensive remediation, "
            "from reproduction to a regression check.\n"
            "- Authority: red tests owned systems; blue fixes root causes; neither "
            "weakens a check to close a finding.\n"
        ),
        "routes": (
            "# Routing Policies\n\n"
            "- New surface or hypothesis -> `red_ops/offensive_test`.\n"
            "- Alert or anomaly -> `blue_ops/detection_analysis`.\n"
            "- Confirmed finding -> `security_review`: rank, assign, demand reproduction.\n"
            "- Prohibited: attacking third parties, exfiltrating data, disabling a check.\n"
        ),
        "stages": {
            "security_review": _stage(
                "Triage findings and incidents, assign owners, and verify the fix",
                "# Stage Instructions: Security Review\n\n"
                "1. A finding needs location, traced untrusted input, impact, and "
                "reproduction steps. Missing any of them -> back to red.\n"
                "2. Rank by real production impact, not a generic severity table.\n"
                "3. A fix needs root cause, smallest patch, and a regression test that "
                "failed before the patch. If the root cause exists elsewhere, name every place.\n"
                "4. Never weaken a check, remove a test, or disable verification.\n"
                "5. Escalate when real data, exposed credentials, a public contract, "
                "or all tenants are affected.\n"
                "6. Close with: cause, file:line, proof, and what remains open.\n",
                ["read_file", "code", "sql_query", "python_sandbox", "http_request",
                 "web_search", "rag_search", "current_datetime",
                 "ask_team_manager", "notify_human", "proactive_alerts"],
                ["crm_create_deal", "crm_update_deal", "send_email"],
                timeout_seconds=240,
                max_llm_calls=10,
                max_cost_usd=0.8,
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
                 "rag_search", "web_search", "current_datetime", "ask_team_manager", "notify_human"],
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
                 "rag_search", "web_search", "current_datetime", "ask_team_manager", "notify_human", "transcribe"],
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
                 "current_datetime", "ask_team_manager", "notify_human", "proactive_alerts"],
                ["python_sandbox"],
            ),
        },
    },
    "media_ops": {
        "identity": (
            "# Media & Growth Workspace\n\n"
            "- ID: `media_ops`\n- Version: `1.0.0`\n"
            "- Purpose: research the market, plan reviewed content, and produce "
            "material without publishing it before approval.\n"
            "- Authority: public/owned sources are evidence; publishing and spend "
            "require human approval.\n"
        ),
        "routes": (
            "# Routing Policies\n\n"
            "- Market signal or competitor fact -> `market_research`.\n"
            "- Brief, audience, angle, or format -> `content_strategy`.\n"
            "- Draft/caption from an approved brief -> `content_production`.\n"
            "- Calendar, campaign, or publication decision -> `media_review`.\n"
            "- Prohibited: invented cases, metrics, credentials, or publishing without approval.\n"
        ),
        "stages": {
            "market_research": _role_stage(
                "Market Research",
                "Collect traceable public signals about audience, competitors, and demand.",
                ["web_search", "knowledge_search", "rag_search", "current_datetime"],
            ),
            "content_strategy": _role_stage(
                "Content Strategy",
                "Turn evidence into a brief with exact fields: topic, audience, problem, objective, angle, evidence, format, CTA, success metric.",
                ["rag_search", "knowledge_search", "current_datetime"],
            ),
            "content_production": _role_stage(
                "Content Production",
                "Draft the approved brief; never invent personal experience, customer cases, performance numbers, or credentials.",
                ["rag_search", "knowledge_search", "current_datetime"],
                side_effects=False,
            ),
            "media_review": _role_stage(
                "Media Review",
                "Review calendar and campaign fit, demand evidence, and approval state before anything reaches a customer.",
                ["ask_team_manager", "notify_human", "crm_pipeline_stats",
                 "crm_list_deals", "current_datetime", "rag_search"],
                ["crm_create_deal", "crm_update_deal", "crm_merge_deals"],
                side_effects=False,
            ),
        },
    },
    "marketing_ops": {
        "identity": (
            "# Marketing Workspace\n\n"
            "- ID: `marketing_ops`\n- Version: `1.0.0`\n"
            "- Purpose: generate measurable demand and hand sourced leads to Sales.\n"
            "- Authority: only approved material goes to a customer; the CRM owns lead state.\n"
        ),
        "routes": (
            "# Routing Policies\n\n"
            "- Campaign or material request -> `demand_generation`.\n"
            "- Budget, published material, or cross-team dependency -> `marketing_review`.\n"
            "- Prohibited: invented price, case, deadline, or customer claim.\n"
        ),
        "stages": {
            "demand_generation": _role_stage(
                "Demand Generation",
                "Build campaign material for a stated audience, pain, offer, channel, cadence, and decision metric; register sourced leads.",
                ["web_search", "knowledge_search", "rag_search", "lead_score",
                 "crm_create_deal", "crm_list_deals", "whatsapp_template_list",
                 "whatsapp_template_draft", "whatsapp_template_lint", "send_email",
                 "calendar_create_event", "current_datetime"],
                ["crm_update_deal", "crm_merge_deals", "crm_delete_deal"],
                side_effects=True,
            ),
            "marketing_review": _role_stage(
                "Marketing Review",
                "Check campaign evidence, target, source attribution, and approvals; escalate spend and customer-facing material.",
                ["ask_team_manager", "request_build", "notify_human", "web_search",
                 "knowledge_search", "rag_search", "lead_score", "crm_list_deals",
                 "crm_pipeline_stats", "whatsapp_template_list",
                 "whatsapp_template_lint", "current_datetime"],
                ["crm_create_deal", "whatsapp_template_draft", "send_email",
                 "calendar_create_event", "crm_update_deal", "crm_merge_deals",
                 "crm_delete_deal"],
                side_effects=False,
            ),
        },
    },
    "customer_success_ops": {
        "identity": (
            "# Customer Success Workspace\n\n"
            "- ID: `customer_success_ops`\n- Version: `1.0.0`\n"
            "- Purpose: support active customers and protect renewal without inventing promises.\n"
            "- Authority: CRM and the customer conversation are the source of truth; "
            "discounts and cancellations need human approval.\n"
        ),
        "routes": (
            "# Routing Policies\n\n"
            "- Inbound customer question -> `support_reply`.\n"
            "- Stale account or renewal risk -> `renewal_follow_up`.\n"
            "- Escalation, churn risk, or discount -> `cs_review`.\n"
            "- Prohibited: claiming new leads, inventing terms, or hiding an angry customer.\n"
        ),
        "stages": {
            "support_reply": _role_stage(
                "Support Reply",
                "Answer the customer's actual question from owned documentation; hand off when the issue is unresolved.",
                ["transcribe", "web_search", "http_request", "read_file"],
                ["crm_update_deal", "crm_delete_deal"],
            ),
            "renewal_follow_up": _role_stage(
                "Renewal Follow-up",
                "Use CRM history and silence windows to state risk, value at stake, and a dated next step.",
                ["crm_list_deals", "crm_stale_deals", "crm_update_deal",
                 "crm_set_follow_up", "send_email", "calendar_create_event",
                 "transcribe", "voice_call", "lead_score", "current_datetime", "rag_search"],
                ["crm_merge_deals", "crm_delete_deal"],
                side_effects=True,
            ),
            "cs_review": _role_stage(
                "Customer Success Review",
                "Rank renewal risk with a value and date per account; escalate large discounts and cancellation threats.",
                ["ask_team_manager", "request_build", "notify_human", "crm_list_deals",
                 "crm_stale_deals", "crm_pipeline_stats", "transcribe", "lead_score",
                 "current_datetime", "rag_search"],
                ["crm_update_deal", "crm_set_follow_up", "send_email",
                 "calendar_create_event", "voice_call", "crm_merge_deals",
                 "crm_delete_deal"],
                side_effects=False,
            ),
        },
    },
    "revops_ops": {
        "identity": (
            "# Revenue & Operations Workspace\n\n"
            "- ID: `revops_ops`\n- Version: `1.0.0`\n"
            "- Purpose: report revenue, audit deals, compile evidence, and watch model/agent "
            "performance from real records.\n"
            "- Authority: numbers come from CRM/SQL with stated window and method; "
            "destructive CRM writes need approval.\n"
        ),
        "routes": (
            "# Routing Policies\n\n"
            "- Forecast, gap, or pipeline hygiene -> `revenue_analysis`.\n"
            "- Manager review of a projection or duplicate -> `revops_review`.\n"
            "- Deal policy breach -> `deal_audit`; proof pack -> `evidence_compile`.\n"
            "- Human deviation -> `human_audit_assist`; price leakage -> `pricing_guard`.\n"
            "- Quality/performance degradation -> `performance_watch`.\n"
            "- Prohibited: projecting without a stated rate or presenting an estimate as measured.\n"
        ),
        "stages": {
            "revenue_analysis": _role_stage(
                "Revenue Analysis",
                "Report weighted pipeline, goal gap, and closed revenue with source, window, and stated rates.",
                ["crm_pipeline_stats", "crm_list_deals", "crm_merge_deals",
                 "calculator", "sql_query", "rag_search", "send_email", "current_datetime"],
                ["crm_update_deal", "crm_delete_deal"],
                side_effects=True,
            ),
            "revops_review": _role_stage(
                "Revenue Operations Review",
                "Reconcile forecast against the prior reading; explain deltas before commenting on results.",
                ["ask_team_manager", "request_build", "notify_human", "crm_pipeline_stats",
                 "crm_list_deals", "calculator", "sql_query", "rag_search", "current_datetime"],
                ["crm_merge_deals", "send_email", "crm_update_deal", "crm_delete_deal"],
                side_effects=False,
            ),
            "deal_audit": _role_stage(
                "Deal Audit",
                "Check a CrmDeal against policy using ledger evidence; record findings with source, calculation, and proof.",
                ["sql_query", "crm_update_deal", "http_request", "calculator", "web_search"],
                ["crm_merge_deals", "crm_delete_deal"],
                side_effects=True,
            ),
            "evidence_compile": _role_stage(
                "Evidence Compile",
                "Assemble the three-layer evidence pack from existing records; never fill gaps with inference.",
                ["sql_query", "read_file", "http_request"],
                ["crm_update_deal", "crm_delete_deal"],
            ),
            "human_audit_assist": _role_stage(
                "Human Audit Assist",
                "Surface human deviations as findings with evidence and a pending action, not as a verdict or punishment.",
                ["sql_query", "web_search", "http_request"],
                ["crm_update_deal", "crm_delete_deal"],
            ),
            "pricing_guard": _role_stage(
                "Pricing Guard",
                "Block out-of-policy proposals with the computed number and the exact rule; force human approval.",
                ["sql_query", "crm_update_deal", "http_request", "calculator"],
                ["crm_merge_deals", "crm_delete_deal"],
                side_effects=True,
            ),
            "performance_watch": _role_stage(
                "Performance Watch",
                "Detect agent/model degradation from measured telemetry; report severity, evidence, and what remains unknown.",
                ["sql_query", "web_search", "http_request", "calculator"],
                ["crm_update_deal", "crm_delete_deal"],
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
                "approval_required": stage["side_effects"],
            }
            (stage_dir / "stage.yaml").write_text(
                yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
            )
            (stage_dir / "CONTEXT.md").write_text(stage["context_md"], encoding="utf-8")
        written.append(ws_dir)
    return written
