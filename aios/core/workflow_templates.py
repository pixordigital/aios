"""Workflow Templates (Phase B) — curated, runnable-checkable templates.

Truthful checks only: uses aios.config.settings and aios.config.PLANS.
No invented promises. Unknown => caller labels as unknown/estimate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from aios.config import PLANS, settings


@dataclass(frozen=True)
class TemplateRequirement:
    key: str
    label: str
    ok: bool | None  # True/False/None(unknown)
    detail: str
    hint: str = ""


@dataclass(frozen=True)
class WorkflowTemplateDef:
    id: str
    name: str
    outcome: str
    steps: list[str]
    needs: list[str]
    safety_notes: list[str]
    # which checks to run
    check_kinds: list[str] = field(default_factory=list)


TEMPLATES: list[WorkflowTemplateDef] = [
    WorkflowTemplateDef(
        id="wa_daily_digest",
        name="WhatsApp daily digest",
        outcome="Send a short daily summary to a WhatsApp number (safe: approval recommended before send).",
        steps=[
            "Trigger: schedule (cron) or manual run",
            "Collect inputs (you provide text/summary source in workflow)",
            "Send via WhatsApp (Evolution) — outbound send should be approval-gated in practice",
        ],
        needs=["WhatsApp (Evolution) connected/configured", "Outbound messaging allowed by your plan", "A destination number/instance ready"],
        safety_notes=[
            "Outbound sends are sensitive. Default-safe: require human approval before sending in production workflows.",
            "This template describes the flow; actual sending uses your configured Evolution/WhatsApp path.",
        ],
        check_kinds=["evolution_config", "plan_evolution", "approval_hint"],
    ),
    WorkflowTemplateDef(
        id="wa_triage_draft_approve_send",
        name="WhatsApp triage → draft reply → approve → send",
        outcome="Triage incoming WhatsApp messages, draft a reply, require approval, then send.",
        steps=[
            "Trigger: webhook/event from WhatsApp inbound (or manual test)",
            "Triage + draft reply (agent or rules)",
            "Approval gate (human) before any outbound send",
            "Send approved reply via WhatsApp (Evolution)",
        ],
        needs=["WhatsApp (Evolution) connected/configured", "Webhook/inbound path available (if automated)", "Approval flow available (dashboard approvals)"],
        safety_notes=[
            "Default-safe: no outbound send without explicit approval.",
            "Triage/draft quality depends on your agent/prompt setup (not guaranteed).",
        ],
        check_kinds=["evolution_config", "plan_evolution", "approval_hint"],
    ),
    WorkflowTemplateDef(
        id="weekly_ops_report_approve_send",
        name="Weekly ops report (approve before send)",
        outcome="Generate a weekly operations summary and send it only after approval.",
        steps=[
            "Trigger: schedule (weekly cron) or manual",
            "Build report from available data (you choose sources)",
            "Approval gate (human) before sending",
            "Send report (email/WhatsApp) via configured channel",
        ],
        needs=["A sending channel configured (e.g. WhatsApp/Evolution or email)", "Data sources you provide", "Approval flow available (dashboard approvals)"],
        safety_notes=[
            "Default-safe: report is not sent without approval.",
            "Costs/limits depend on models/tools you add; this gallery does not invent numbers.",
        ],
        check_kinds=["plan_channels", "approval_hint"],
    ),
]


def _check_evolution_config() -> TemplateRequirement:
    url = (getattr(settings, "evolution_server_url", "") or "").strip()
    key = (getattr(settings, "evolution_api_key", "") or "").strip()
    # Treat obvious placeholders as not configured (truthful)
    bad_key = key in {"", "evolution_secret_change_me", "changeme"}
    ok = bool(url) and (not bad_key)
    if ok:
        detail = "Evolution server URL and API key appear set in config/env."
    else:
        missing = []
        if not url:
            missing.append("EVOLUTION_SERVER_URL/evolution_server_url")
        if bad_key:
            missing.append("EVOLUTION_API_KEY/evolution_api_key")
        detail = "Missing/placeholder: " + ", ".join(missing) + "."
    hint = "Set Evolution config in env (see .env.example / deployment docs). No secrets shown here."
    return TemplateRequirement(
        key="evolution_config",
        label="WhatsApp (Evolution) config",
        ok=ok,
        detail=detail,
        hint=hint if not ok else "",
    )


def _check_plan_evolution(org_plan: str | None) -> TemplateRequirement:
    plan = (org_plan or "free").strip().lower()
    plan_cfg = PLANS.get(plan) or PLANS.get("free") or {}
    max_inst = int(plan_cfg.get("max_evolution_instances", 0) or 0)
    channels = plan_cfg.get("channels", [])
    allows_evo = channels == "__all__" or ("evolution" in channels)
    ok = allows_evo and max_inst > 0
    plan_name = str(plan_cfg.get("name", plan))
    if ok:
        detail = f"Plan '{plan_name}' allows Evolution channel (max instances: {max_inst})."
    else:
        detail = f"Plan '{plan_name}' does not allow Evolution channel or allows 0 instances."
    hint = "Upgrade/change plan to enable WhatsApp (Evolution) where available." if not ok else ""
    return TemplateRequirement(
        key="plan_evolution",
        label="Plan allows WhatsApp (Evolution)",
        ok=ok,
        detail=detail,
        hint=hint,
    )


def _check_plan_channels(org_plan: str | None) -> TemplateRequirement:
    plan = (org_plan or "free").strip().lower()
    plan_cfg = PLANS.get(plan) or PLANS.get("free") or {}
    channels = plan_cfg.get("channels", [])
    if channels == "__all__":
        detail = f"Plan '{plan_cfg.get('name', plan)}' allows all channels (per config)."
        ok = True
    else:
        detail = f"Plan '{plan_cfg.get('name', plan)}' allows channels: {', '.join(channels) if channels else 'none listed'}."
        ok = len(channels) > 0
    hint = "" if ok else "Check plan/channel availability in settings."
    return TemplateRequirement(
        key="plan_channels",
        label="Sending channels (plan)",
        ok=ok,
        detail=detail,
        hint=hint,
    )


def _check_approval_hint() -> TemplateRequirement:
    # We cannot prove UI route exists from config, but we know approvals exist in product.
    return TemplateRequirement(
        key="approval_hint",
        label="Approval flow (recommended)",
        ok=None,
        detail="AIOS has approval flows (dashboard). For outbound sends/reports, keep approval gates enabled (default-safe).",
        hint="Use Approvals in dashboard before sending outbound messages/reports.",
    )


def evaluate_template(tpl: WorkflowTemplateDef, org_plan: str | None) -> dict[str, Any]:
    reqs: list[TemplateRequirement] = []
    for k in tpl.check_kinds:
        if k == "evolution_config":
            reqs.append(_check_evolution_config())
        elif k == "plan_evolution":
            reqs.append(_check_plan_evolution(org_plan))
        elif k == "plan_channels":
            reqs.append(_check_plan_channels(org_plan))
        elif k == "approval_hint":
            reqs.append(_check_approval_hint())
    # runnable if all non-None checks are True; None checks don't block but are warnings
    blocking = [r for r in reqs if r.ok is False]
    unknowns = [r for r in reqs if r.ok is None]
    runnable = len(blocking) == 0
    status = "runnable" if runnable and not unknowns else ("runnable_with_caveats" if runnable else "blocked")
    return {
        "id": tpl.id,
        "name": tpl.name,
        "outcome": tpl.outcome,
        "steps": list(tpl.steps),
        "needs": list(tpl.needs),
        "safety_notes": list(tpl.safety_notes),
        "status": status,
        "runnable": runnable,
        "requirements": [asdict(r) for r in reqs],
        "blocking": [asdict(r) for r in blocking],
        "unknowns": [asdict(r) for r in unknowns],
    }


def list_evaluated_templates(org_plan: str | None) -> list[dict[str, Any]]:
    return [evaluate_template(t, org_plan) for t in TEMPLATES]