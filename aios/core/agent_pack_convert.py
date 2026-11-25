"""Converters: AIOS templates/ICM workspaces -> Agent Pack manifests.

Explicit capability_loss; never silent drop. Deterministic for same input.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aios.core.agent_pack import (
    AgentPackManifest,
    AgentPackValidationError,
    PackApprovalPolicy,
    PackChangelogEntry,
    PackIdentity,
    PackMemoryScope,
    PackPrompt,
    PackProvenance,
    PackRoutine,
    PackRuntimeTarget,
    PackToolPolicy,
    manifest_fingerprint,
    validate_agent_pack,
)
from aios.icm.team_workspaces import AGENT_EVENTS, AGENT_STAGES, TEAM_WORKSPACES
from aios.templates import TEMPLATES, _SCAFFOLD_MARKER, apply_template
from aios.templates.solutions import SOLUTIONS

LossSeverity = Literal["info", "warn", "high"]
LOSS_CODES = {
    "python_callable_not_portable",
    "schema_field_unmapped",
    "policy_normalized",
    "scaffold_applied",
    "binding_external",
    "identity_alias",
    "runtime_defaulted",
    "solution_overlay_unmodeled",
    "unknown_tool_or_risk",
    "prompt_variables_unparsed",
}

# Template key -> ICM AGENT_STAGES agent name (best-effort, explicit where known).
_TEMPLATE_TO_ICM_AGENT: dict[str, str] = {
    "sdr": "sales-sdr",
    "closer": "sales-closer",
    "support": "Support",
    "data_analyst": "Data Analyst",
    "data_scientist": "Data Scientist",
    "deal_auditor": "Deal Auditor",
    "pricing_guardian": "Pricing Guardian",
    "evidence_compiler": "Evidence Compiler",
    "performance_watcher": "Performance Watcher",
    "human_auditor": "Human Auditor Assistant",
    "frontend": "dev-frontend",
    "backend": "dev-backend",
    "red": "red-agent",
    "blue": "blue-agent",
    "media_manager": "Media Manager",
    "market_intelligence": "Market Intelligence Researcher",
    "content_strategist": "Content Strategist",
    "content_producer": "Content Producer",
    "marketing": "Marketing",
    "manager_marketing": "Manager Marketing",
    "customer_success": "Customer Success",
    "manager_cs": "Manager Cs",
    "revops": "Revops",
    "manager_revops": "Manager Revops",
    "manager_sales": "sales-manager",
    "manager_dev": "dev-manager",
    "manager_red": "security-manager",
    "manager_blue": "security-manager",
    "manager_data": "data-manager",
}

# Known risky tools best-effort mapping; unknown tools omitted from risk_classes with loss.
_TOOL_RISK_CLASSES: dict[str, str] = {
    "read_file": "read",
    "web_search": "read",
    "rag_search": "read",
    "knowledge_search": "read",
    "sql_query": "read",
    "http_request": "side_effect",
    "http_get": "read",
    "send_email": "side_effect",
    "crm_create_deal": "write",
    "crm_update_deal": "write",
    "crm_merge_deals": "destructive",
    "crm_delete_deal": "destructive",
    "crm_list_deals": "read",
    "crm_stale_deals": "read",
    "crm_pipeline_stats": "read",
    "crm_set_follow_up": "write",
    "lead_score": "read",
    "lead_save": "write",
    "lead_list": "read",
    "lead_review": "write",
    "python_sandbox": "side_effect",
    "code": "write",
    "notify_human": "side_effect",
    "request_build": "side_effect",
    "ask_team_manager": "read",
    "calculator": "read",
    "current_datetime": "read",
    "calendar_create_event": "side_effect",
    "cal_booking": "side_effect",
    "voice_call": "side_effect",
    "transcribe": "read",
    "whatsapp_template": "side_effect",
    "whatsapp_template_list": "read",
    "whatsapp_template_draft": "write",
    "whatsapp_template_lint": "read",
    "hubspot": "side_effect",
    "pipedrive": "side_effect",
    "rdstation": "side_effect",
    "proactive_alerts": "read",
}

_RISK_CLASS_VALUES = {"read", "write", "side_effect", "destructive"}


class CapabilityLossEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    severity: LossSeverity
    reason_code: str
    source_path: str
    source_field: str
    detail: str
    portable_alternative: str | None = None


class PackConversionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: AgentPackManifest
    capability_loss: list[CapabilityLossEntry]
    fingerprint: str


_CONVERSION_CREATED_AT = "2026-11-25T00:00:00Z"


def _now_iso() -> str:
    # Deterministic for pack conversion outputs; conversion metadata date is fixed.
    return _CONVERSION_CREATED_AT


def _slugify(value: str) -> str:
    s = re.sub(r"[^a-z0-9_-]+", "-", value.lower().strip())
    s = re.sub(r"-{2,}", "-", s).strip("-_")
    if not s:
        s = "unknown"
    if not s[0].isalpha():
        s = f"t-{s}"
    return s[:64]


def _humanize(key: str) -> str:
    return " ".join(part.capitalize() for part in re.split(r"[_\-\s]+", key) if part)


def _first_non_empty_prompt_line(prompt: str) -> str:
    for line in prompt.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:2000]
    return ""


def _extract_prompt_variables(prompt: str) -> tuple[list[str], bool]:
    # Best-effort: {{var}} and {{obj.field}}; uncertain for complex expressions.
    found = re.findall(r"\{\{\s*([^{}]+?)\s*\}\}", prompt)
    vars_out: list[str] = []
    uncertain = False
    for raw in found:
        token = raw.strip()
        # normalize to simple identifier-like variable name
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", token):
            norm = token.replace(".", "_")
            if norm not in vars_out:
                vars_out.append(norm)
        else:
            uncertain = True
    return vars_out[:64], uncertain


def _canonical_payload(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _checksum_fingerprint(data: dict[str, Any]) -> str:
    payload = json.loads(json.dumps(data, mode="json") if hasattr(data, "mode") else json.dumps(data))
    if isinstance(payload, str):
        payload = json.loads(payload)
    prov = payload.get("provenance")
    if isinstance(prov, dict):
        prov["checksum_sha256"] = None
        prov["signature"] = None
    return hashlib.sha256(_canonical_payload(payload).encode("utf-8")).hexdigest()


def _checksum_for_manifest_dict(data: dict[str, Any]) -> str:
    d = json.loads(_canonical_payload(data))
    prov = d.get("provenance")
    if isinstance(prov, dict):
        prov["checksum_sha256"] = None
        prov["signature"] = None
    return hashlib.sha256(_canonical_payload(d).encode("utf-8")).hexdigest()


def _loss(
    loss_id: str,
    severity: LossSeverity,
    reason_code: str,
    source_path: str,
    source_field: str,
    detail: str,
    portable_alternative: str | None = None,
) -> CapabilityLossEntry:
    if reason_code not in LOSS_CODES:
        raise ValueError(f"unknown loss reason_code: {reason_code}")
    return CapabilityLossEntry(
        id=_slugify(loss_id)[:63],
        severity=severity,
        reason_code=reason_code,
        source_path=source_path,
        source_field=source_field,
        detail=detail[:500],
        portable_alternative=portable_alternative[:500] if portable_alternative else None,
    )


def _dedupe_losses(losses: list[CapabilityLossEntry]) -> list[CapabilityLossEntry]:
    seen: set[tuple[str, str, str, str, str]] = set()
    out: list[CapabilityLossEntry] = []
    for item in losses:
        k = (item.id, item.reason_code, item.source_path, item.source_field, item.detail)
        if k in seen:
            continue
        seen.add(k)
        out.append(item)
    return sorted(out, key=lambda x: (x.severity, x.reason_code, x.source_field, x.id, x.detail))


def _normalize_tools(
    raw_tools: Any,
    governance: dict[str, Any] | None,
    *,
    source_path: str,
    losses: list[CapabilityLossEntry],
) -> tuple[list[str], list[str], dict[str, str]]:
    allowed: list[str] = []
    denied: list[str] = []
    risk_classes: dict[str, str] = {}

    if raw_tools == "__all__":
        losses.append(
            _loss(
                f"{source_path}-policy-normalized",
                "warn",
                "policy_normalized",
                source_path,
                "tools",
                "allowed_tools was '__all__'; normalized to empty allowlist with explicit loss",
                portable_alternative="Declare explicit allowed_tools in pack",
            )
        )
        allowed = []
    elif isinstance(raw_tools, list):
        for t in raw_tools:
            if isinstance(t, str) and t.strip():
                if t == "__all__":
                    losses.append(
                        _loss(
                            f"{source_path}-policy-normalized-item",
                            "warn",
                            "policy_normalized",
                            source_path,
                            "tools",
                            "tool entry '__all__' normalized out of allowed_tools",
                            portable_alternative="Declare explicit allowed_tools in pack",
                        )
                    )
                else:
                    allowed.append(t.strip())
    elif raw_tools is None:
        pass
    else:
        losses.append(
            _loss(
                f"{source_path}-tools-unmapped",
                "warn",
                "schema_field_unmapped",
                source_path,
                "tools",
                f"tools field type {type(raw_tools).__name__} not directly portable",
                portable_alternative="Use explicit list[str] allowed_tools",
            )
        )

    gov = governance if isinstance(governance, dict) else {}
    gov_denied = gov.get("denied_tools")
    if isinstance(gov_denied, list):
        for t in gov_denied:
            if isinstance(t, str) and t.strip():
                denied.append(t.strip())

    # Denied wins: remove from allowed.
    denied_set = set(denied)
    if denied_set:
        allowed = [t for t in allowed if t not in denied_set]

    allowed = sorted(dict.fromkeys(allowed))
    denied = sorted(dict.fromkeys(denied))

    for t in allowed:
        rc = _TOOL_RISK_CLASSES.get(t)
        if rc in _RISK_CLASS_VALUES:
            risk_classes[t] = rc
        else:
            losses.append(
                _loss(
                    f"{source_path}-unknown-tool-{t}",
                    "info",
                    "unknown_tool_or_risk",
                    source_path,
                    "tools",
                    f"tool '{t}' has no known risk class mapping; omitted from risk_classes",
                    portable_alternative="Set risk_classes explicitly in pack",
                )
            )

    return allowed, denied, dict(sorted(risk_classes.items()))


def _memory_scope_from_template(template: dict[str, Any], source_path: str, losses: list[CapabilityLossEntry]) -> PackMemoryScope:
    cfg = template.get("memory_config")
    scopes: list[Literal["conversation", "agent", "team", "org"]] = ["conversation", "agent"]
    max_short = 100
    long_term = True
    episodic = True
    if isinstance(cfg, dict):
        short = cfg.get("short_term")
        if isinstance(short, dict):
            msm = short.get("max_messages")
            if isinstance(msm, int):
                max_short = max(1, min(2000, msm))
        lt = cfg.get("long_term")
        if isinstance(lt, dict) and isinstance(lt.get("enabled"), bool):
            long_term = lt["enabled"]
        ep = cfg.get("episodic")
        if isinstance(ep, dict) and isinstance(ep.get("enabled"), bool):
            episodic = ep["enabled"]
        for k in ("scopes", "redact_patterns"):
            if k in cfg and k not in {"short_term", "long_term", "episodic"}:
                pass
        # copy unsupported extra fields as loss
        known = {"short_term", "long_term", "episodic"}
        extra = sorted(set(cfg.keys()) - known)
        for k in extra:
            if k == "scopes" and isinstance(cfg[k], list):
                vals = [v for v in cfg[k] if v in {"conversation", "agent", "team", "org"}]
                if vals:
                    scopes = list(dict.fromkeys(vals))  # type: ignore[assignment]
                continue
            losses.append(
                _loss(
                    f"{source_path}-memory-{k}",
                    "info",
                    "schema_field_unmapped",
                    source_path,
                    f"memory_config.{k}",
                    f"memory_config.{k} not directly mapped; preserved only if representable",
                    portable_alternative="Map field explicitly in memory_scope",
                )
            )
    elif cfg is not None:
        losses.append(
            _loss(
                f"{source_path}-memory-unmapped",
                "warn",
                "schema_field_unmapped",
                source_path,
                "memory_config",
                "memory_config not a mapping; defaults applied",
            )
        )

    if not scopes:
        scopes = ["conversation", "agent"]
    return PackMemoryScope(
        scopes=scopes,
        max_short_term_messages=max_short,
        long_term_enabled=long_term,
        episodic_enabled=episodic,
        redact_patterns=[],
    )


def _approvals_from_template(
    template: dict[str, Any],
    *,
    source_path: str,
    side_effects: bool = False,
    losses: list[CapabilityLossEntry],
) -> PackApprovalPolicy:
    gov = template.get("governance_config")
    gov = gov if isinstance(gov, dict) else {}
    hitl = bool(gov.get("hitl_enabled")) or side_effects
    required_for: list[str] = []
    for k in ("required_for", "approval_required_tools"):
        v = gov.get(k)
        if isinstance(v, list):
            required_for.extend([str(x) for x in v if isinstance(x, str) and x.strip()])
    side_fx = gov.get("side_effects")
    if isinstance(side_fx, list):
        required_for.extend([str(x) for x in side_fx if isinstance(x, str) and x.strip()])
    required_for = sorted(dict.fromkeys(required_for))

    mode: Literal["none", "ask_tools", "ask_all", "policy"] = "ask_tools" if hitl or required_for else "ask_tools"
    # If explicitly autonomous and no hitl/side effects/required_for, keep ask_tools? Never fabricate preapproval.
    # Spec: "side_effects/hitl_enabled => mode ask_tools or policy; required_for from side_effects/approval_required; approval_ttl_seconds 300 default; explicit_preapproved_allowed False always. never fabricate."
    if not hitl and not required_for and isinstance(gov.get("autonomous"), bool) and gov.get("autonomous") is True:
        # Autonomous template without hitl - still not explicit preapproval; represent as ask_tools with loss? Keep safe default.
        losses.append(
            _loss(
                f"{source_path}-approval-autonomous",
                "info",
                "policy_normalized",
                source_path,
                "governance_config.autonomous",
                "autonomous=true normalized to ask_tools; explicit_preapproved_allowed remains false",
                portable_alternative="Set approvals.mode/policy explicitly in pack",
            )
        )
        mode = "ask_tools"

    ttl = gov.get("approval_ttl_seconds", 300)
    if not isinstance(ttl, int):
        ttl = 300
    ttl = max(30, min(3600, ttl))
    return PackApprovalPolicy(
        mode=mode,
        required_for=required_for,
        approval_ttl_seconds=ttl,
        explicit_preapproved_allowed=False,
    )


def _runtime_targets_default(source_path: str, losses: list[CapabilityLossEntry]) -> list[PackRuntimeTarget]:
    losses.append(
        _loss(
            f"{source_path}-runtime-defaulted",
            "info",
            "runtime_defaulted",
            source_path,
            "runtime_targets",
            "runtime_targets defaulted to [local_proc] with empty entrypoint",
            portable_alternative="Set explicit runtime_targets in pack",
        )
    )
    return [PackRuntimeTarget(target="local_proc", entrypoint="", image=None, resources={})]


def _provenance(source: str, created_at: str) -> dict[str, Any]:
    return {
        "source": source[:255],
        "created_by": "agent_pack_convert",
        "created_at": created_at,
        "checksum_sha256": None,
        "signature": None,
        "parent_fingerprint": None,
    }


def _build_manifest_dict(
    *,
    version: str,
    identity: dict[str, Any],
    prompt: dict[str, Any],
    tools: dict[str, Any],
    routines: list[dict[str, Any]],
    approvals: dict[str, Any],
    memory_scope: dict[str, Any],
    runtime_targets: list[dict[str, Any]],
    changelog: list[dict[str, Any]],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    data = {
        "schema_version": "1.0.0",
        "version": version,
        "identity": identity,
        "prompt": prompt,
        "tools": tools,
        "routines": routines,
        "approvals": approvals,
        "memory_scope": memory_scope,
        "runtime_targets": runtime_targets,
        "changelog": changelog,
        "provenance": provenance,
    }
    data["provenance"]["checksum_sha256"] = _checksum_for_manifest_dict(data)
    return data


def _result_from_manifest(manifest: AgentPackManifest, losses: list[CapabilityLossEntry]) -> PackConversionResult:
    ordered_losses = _dedupe_losses(losses)
    return PackConversionResult(
        manifest=manifest,
        capability_loss=ordered_losses,
        fingerprint=manifest_fingerprint(manifest),
    )


def _template_source_path(template_key: str) -> str:
    # best-effort stable source path
    return f"aios/templates/{template_key}.py"


def convert_template(template_key: str, *, owner: str = "", provenance_source: str | None = None) -> PackConversionResult:
    if template_key not in TEMPLATES:
        raise KeyError(f"unknown template: {template_key}")
    raw_template = TEMPLATES[template_key]
    source_path = provenance_source or _template_source_path(template_key)
    losses: list[CapabilityLossEntry] = []

    # identity
    agent_type = str(raw_template.get("agent_type") or template_key)
    raw_prompt = str(raw_template.get("system_prompt") or "")
    scaffolded = apply_template(template_key)
    system_prompt = str(scaffolded.get("system_prompt") or raw_prompt)
    scaffold_applied = _SCAFFOLD_MARKER not in raw_prompt
    if scaffold_applied:
        losses.append(
            _loss(
                f"{template_key}-scaffold-applied",
                "info",
                "scaffold_applied",
                source_path,
                "system_prompt",
                "Scaffold marker absent in raw template; apply_template scaffold appended",
                portable_alternative="Include scaffold marker in source template",
            )
        )

    variables, uncertain = _extract_prompt_variables(system_prompt)
    if uncertain:
        losses.append(
            _loss(
                f"{template_key}-prompt-vars-unparsed",
                "warn",
                "prompt_variables_unparsed",
                source_path,
                "prompt.variables",
                "Some {{...}} prompt variables could not be safely parsed; extracted best-effort",
                portable_alternative="Use simple {{variable_name}} placeholders",
            )
        )

    # tools
    allowed_tools, denied_tools, risk_classes = _normalize_tools(
        raw_template.get("tools"),
        raw_template.get("governance_config") if isinstance(raw_template.get("governance_config"), dict) else None,
        source_path=source_path,
        losses=losses,
    )

    # routines from AGENT_EVENTS/AGENT_STAGES
    icm_agent = _TEMPLATE_TO_ICM_AGENT.get(template_key)
    routines: list[dict[str, Any]] = []
    stage_side_effects = False
    if icm_agent:
        ws_stage = AGENT_STAGES.get(icm_agent)
        stage_ref = None
        if ws_stage:
            ws_id, stage_id = ws_stage
            stage_ref = f"icm:{ws_id}/{stage_id}"
            stage_def = TEAM_WORKSPACES.get(ws_id, {}).get("stages", {}).get(stage_id, {})
            stage_side_effects = bool(stage_def.get("side_effects"))
            # stage denied tools: union wins
            stage_denied = stage_def.get("denied_tools")
            if isinstance(stage_denied, list):
                extra_denied = [t for t in stage_denied if isinstance(t, str) and t.strip()]
                if extra_denied:
                    merged_denied = sorted(dict.fromkeys(denied_tools + extra_denied))
                    if merged_denied != denied_tools:
                        denied_tools = merged_denied
                        allowed_tools = sorted([t for t in allowed_tools if t not in set(denied_tools)])
                        for t in list(risk_classes.keys()):
                            if t in denied_tools:
                                risk_classes.pop(t, None)
        events = AGENT_EVENTS.get(icm_agent, [])
        for ev in events:
            routines.append(
                {
                    "id": _slugify(f"{template_key}-{ev.replace('.', '-').replace('*', 'wildcard')}")[:63],
                    "trigger": f"event:{ev}",
                    "workflow_id": None,
                    "stage_ref": stage_ref,
                    "enabled": True,
                }
            )
    routines = sorted(routines, key=lambda r: r["id"])

    approvals = _approvals_from_template(raw_template, source_path=source_path, side_effects=stage_side_effects, losses=losses)
    memory_scope = _memory_scope_from_template(raw_template, source_path, losses)
    runtime_targets = _runtime_targets_default(source_path, losses)

    now = _now_iso()
    changelog = [
        {
            "version": "1.0.0",
            "date": "2026-11-25",
            "summary": "Converted from AIOS template",
            "author": "agent_pack_convert",
        }
    ]
    identity = {
        "id": _slugify(f"template-{template_key}"),
        "name": _humanize(template_key),
        "agent_type": agent_type[:64],
        "description": _first_non_empty_prompt_line(raw_prompt),
        "owner": owner[:120],
        "tags": sorted(dict.fromkeys(["template", template_key])),
    }
    prompt = {
        "system_prompt": system_prompt,
        "variables": sorted(dict.fromkeys(variables)),
        "scaffold_required": True,
    }
    tools = {
        "allowed_tools": allowed_tools,
        "denied_tools": denied_tools,
        "risk_classes": dict(sorted(risk_classes.items())),
    }

    manifest_dict = _build_manifest_dict(
        version="1.0.0",
        identity=identity,
        prompt=prompt,
        tools=tools,
        routines=routines,
        approvals=approvals.model_dump(mode="json"),
        memory_scope=memory_scope.model_dump(mode="json"),
        runtime_targets=[rt.model_dump(mode="json") for rt in runtime_targets],
        changelog=changelog,
        provenance=_provenance(source_path, now),
    )

    manifest = validate_agent_pack(manifest_dict)
    return _result_from_manifest(manifest, losses)


def convert_all_templates(*, fail_on_high: bool = False) -> list[PackConversionResult]:
    results: list[PackConversionResult] = []
    for key in sorted(TEMPLATES.keys()):
        # solutions are templates? no, solutions are in solutions.py; TEMPLATES has template keys.
        res = convert_template(key)
        if fail_on_high and any(e.severity == "high" for e in res.capability_loss):
            highs = [e for e in res.capability_loss if e.severity == "high"]
            raise AgentPackValidationError(
                f"high-severity capability loss for template {key}: {[h.id for h in highs]}",
                field=key,
            )
        results.append(res)
    return results


def convert_icm_stage(agent_name: str, *, owner: str = "") -> PackConversionResult:
    if agent_name not in AGENT_STAGES:
        raise KeyError(f"unknown ICM agent: {agent_name}")
    ws_id, stage_id = AGENT_STAGES[agent_name]
    ws = TEAM_WORKSPACES.get(ws_id)
    if not ws:
        raise KeyError(f"unknown ICM workspace: {ws_id}")
    stage = ws.get("stages", {}).get(stage_id)
    if not stage:
        raise KeyError(f"unknown ICM stage: {ws_id}/{stage_id}")

    source_path = f"aios/icm/team_workspaces.py:{ws_id}/{stage_id}"
    losses: list[CapabilityLossEntry] = []

    allowed = stage.get("allowed_tools") or []
    denied = stage.get("denied_tools") or []
    allowed_tools, denied_tools, risk_classes = _normalize_tools(
        allowed,
        {"denied_tools": denied} if isinstance(denied, list) else None,
        source_path=source_path,
        losses=losses,
    )

    events = AGENT_EVENTS.get(agent_name, [])
    stage_ref = f"icm:{ws_id}/{stage_id}"
    routines = []
    for ev in events:
        routines.append(
            {
                "id": _slugify(f"{_slugify(agent_name)}-{ev.replace('.', '-').replace('*', 'wildcard')}")[:63],
                "trigger": f"event:{ev}",
                "workflow_id": None,
                "stage_ref": stage_ref,
                "enabled": True,
            }
        )
    routines = sorted(routines, key=lambda r: r["id"])

    side_effects = bool(stage.get("side_effects"))
    approval_required = bool(stage.get("approval_required", side_effects))
    template_like = {
        "governance_config": {
            "hitl_enabled": approval_required or side_effects,
            "side_effects": [t for t in allowed_tools if risk_classes.get(t) in {"side_effect", "destructive"}] if side_effects else [],
        }
    }
    approvals = _approvals_from_template(template_like, source_path=source_path, side_effects=side_effects, losses=losses)

    context_md = str(stage.get("context_md") or stage.get("description") or agent_name)
    prompt = {
        "system_prompt": context_md.strip() or f"ICM stage {agent_name}",
        "variables": [],
        "scaffold_required": False,
    }

    identity = {
        "id": _slugify(f"icm-{ws_id}-{stage_id}"),
        "name": agent_name,
        "agent_type": _slugify(agent_name.replace(" ", "_")),
        "description": str(stage.get("description") or "")[:2000],
        "owner": owner[:120],
        "tags": sorted(dict.fromkeys(["icm", ws_id, stage_id])),
    }

    now = _now_iso()
    manifest_dict = _build_manifest_dict(
        version="1.0.0",
        identity=identity,
        prompt=prompt,
        tools={"allowed_tools": allowed_tools, "denied_tools": denied_tools, "risk_classes": risk_classes},
        routines=routines,
        approvals=approvals.model_dump(mode="json"),
        memory_scope=PackMemoryScope().model_dump(mode="json"),
        runtime_targets=[rt.model_dump(mode="json") for rt in _runtime_targets_default(source_path, losses)],
        changelog=[{"version": "1.0.0", "date": "2026-11-25", "summary": "Converted from AIOS template", "author": "agent_pack_convert"}],
        provenance=_provenance(source_path, now),
    )
    manifest = validate_agent_pack(manifest_dict)
    return _result_from_manifest(manifest, losses)


def convert_solutions() -> list[PackConversionResult]:
    """Convert solution packs to explicit loss-marked results.

    Solutions are overlay/product bundles, not full templates; we emit a minimal
    valid manifest per solution and mark unmodeled overlay fields as loss. Never silent drop.
    """
    results: list[PackConversionResult] = []
    for key in sorted(SOLUTIONS.keys()):
        sol = SOLUTIONS[key]
        source_path = f"aios/templates/solutions.py:{key}"
        losses: list[CapabilityLossEntry] = []
        losses.append(
            _loss(
                f"solution-{key}-overlay-unmodeled",
                "high",
                "solution_overlay_unmodeled",
                source_path,
                "solution",
                f"Solution '{key}' is a product overlay; channel/addon/bundle semantics not fully portable",
                portable_alternative="Model channel/addon as explicit pack extensions or separate deployment config",
            )
        )
        # addon may contain python-ish/runtime binding assumptions? treat as prompt content but mark binding external
        if sol.get("channel"):
            losses.append(
                _loss(
                    f"solution-{key}-binding-external",
                    "warn",
                    "binding_external",
                    source_path,
                    "channel",
                    f"Solution channel '{sol.get('channel')}' requires external binding",
                    portable_alternative="Declare channel binding in deployment/runtime config",
                )
            )

        raw_tools = sol.get("tools", [])
        allowed_tools, denied_tools, risk_classes = _normalize_tools(raw_tools, None, source_path=source_path, losses=losses)
        system_prompt = str(sol.get("addon") or sol.get("desc") or key)
        variables, uncertain = _extract_prompt_variables(system_prompt)
        if uncertain:
            losses.append(
                _loss(
                    f"solution-{key}-prompt-vars-unparsed",
                    "warn",
                    "prompt_variables_unparsed",
                    source_path,
                    "prompt.variables",
                    "Some {{...}} prompt variables could not be safely parsed; extracted best-effort",
                )
            )

        now = _now_iso()
        manifest_dict = _build_manifest_dict(
            version="1.0.0",
            identity={
                "id": _slugify(f"solution-{key}"),
                "name": str(sol.get("title") or _humanize(key))[:120],
                "agent_type": str(sol.get("agent_type") or "custom")[:64],
                "description": str(sol.get("desc") or "")[:2000],
                "owner": "",
                "tags": sorted(dict.fromkeys(["solution", key])),
            },
            prompt={
                "system_prompt": system_prompt,
                "variables": sorted(dict.fromkeys(variables)),
                "scaffold_required": False,
            },
            tools={"allowed_tools": allowed_tools, "denied_tools": denied_tools, "risk_classes": risk_classes},
            routines=[],
            approvals=PackApprovalPolicy(mode="ask_tools", explicit_preapproved_allowed=False).model_dump(mode="json"),
            memory_scope=PackMemoryScope().model_dump(mode="json"),
            runtime_targets=[rt.model_dump(mode="json") for rt in _runtime_targets_default(source_path, losses)],
            changelog=[{"version": "1.0.0", "date": "2026-11-25", "summary": "Converted from AIOS template", "author": "agent_pack_convert"}],
            provenance=_provenance(source_path, now),
        )
        manifest = validate_agent_pack(manifest_dict)
        results.append(_result_from_manifest(manifest, losses))
    return results
