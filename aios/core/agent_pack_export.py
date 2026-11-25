"""Export-only AgentPack adapters.

Deterministic bundle dir + reports. No install, no runtime config mutation,
no network, no shell.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aios.core.agent_pack import AgentPackManifest, AgentPackValidationError, manifest_fingerprint, validate_agent_pack

ExportTarget = Literal["claude_code", "codex", "opencode", "openclaw"]

_TARGETS: tuple[str, ...] = ("claude_code", "codex", "opencode", "openclaw")
_LOSS_STATUSES = {"supported", "partial", "unsupported", "transformed", "denied"}
_LOSS_SEVERITIES = {"info", "warn", "blocker"}
_STATUS_RANK = {"denied": 4, "unsupported": 3, "transformed": 2, "partial": 1, "supported": 0}
_SEVERITY_RANK = {"blocker": 3, "warn": 2, "info": 1}
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class ExportResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target: ExportTarget
    output_dir: str
    bundle_manifest_path: str
    capability_loss_report_path: str
    provenance_path: str
    files: list[str]
    bundle_sha256: str
    fingerprint: str


class CapabilityLossItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field_path: str
    status: Literal["supported", "partial", "unsupported", "transformed", "denied"]
    severity: Literal["info", "warn", "blocker"]
    reason: str
    source_ref: str
    target_ref: str | None = None
    remediation: str | None = None


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_json(data: Any) -> str:
    return _sha256_bytes(_canonical_json(data).encode("utf-8"))


def _now_iso() -> str:
    # Deterministic timestamp not possible from wall clock; use fixed export metadata format? 
    # Spec says created_at in bundle manifest; keep deterministic by using manifest provenance.created_at
    # fallback to fixed epoch-like stable value. No clock dependence for determinism.
    return "1970-01-01T00:00:00Z"


def _ensure_safe_output_dir(output_dir: str | Path) -> Path:
    if not isinstance(output_dir, (str, Path)) or str(output_dir) == "":
        raise AgentPackValidationError("output_dir must be a non-empty path", field="output_dir")
    p = Path(output_dir)
    # do not resolve symlinks away before checks; reject if any existing component is symlink
    if p.exists():
        if p.is_symlink():
            raise AgentPackValidationError("output_dir must not be a symlink", field="output_dir")
        if not p.is_dir():
            raise AgentPackValidationError("output_dir must be a directory", field="output_dir")
    # validate path parts - no traversal via .. 
    for part in p.parts:
        if part == "..":
            raise AgentPackValidationError("output_dir contains path traversal", field="output_dir")
    resolved = p.resolve()
    return resolved


def _safe_rel_path(output_dir: Path, rel: str) -> Path:
    if not isinstance(rel, str) or not rel:
        raise AgentPackValidationError("invalid export path", field=rel)
    if rel.startswith("/") or rel.startswith("\\"):
        raise AgentPackValidationError("absolute export path rejected", field=rel)
    if "\\" in rel:
        raise AgentPackValidationError("backslash in export path rejected", field=rel)
    rp = Path(rel)
    if any(part in {"..", ""} for part in rp.parts):
        raise AgentPackValidationError("path traversal rejected", field=rel)
    # refuse hidden/odd? no, .claude/.opencode needed. but refuse symlink escape on write
    target = (output_dir / rp)
    resolved = target.resolve()
    try:
        resolved.relative_to(output_dir.resolve())
    except Exception as exc:
        raise AgentPackValidationError("path escapes output_dir", field=rel) from exc
    # refuse if any existing parent/file in rel path is symlink
    cur = output_dir
    for part in rp.parts:
        cur = cur / part
        if cur.is_symlink():
            raise AgentPackValidationError("symlink in output path rejected", field=rel)
    return target


def _write_file(output_dir: Path, rel: str, content: str | bytes) -> dict[str, Any]:
    target = _safe_rel_path(output_dir, rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    # recheck parents for symlink escape after mkdir
    cur = output_dir
    for part in Path(rel).parts[:-1]:
        cur = cur / part
        if cur.is_symlink():
            raise AgentPackValidationError("symlink in output path rejected", field=rel)
    raw = content if isinstance(content, bytes) else content.encode("utf-8")
    if len(raw) > 2 * 1024 * 1024:
        raise AgentPackValidationError("export file exceeds size limit", field=rel)
    target.write_bytes(raw)
    return {
        "path": rel,
        "sha256": _sha256_bytes(raw),
        "bytes": len(raw),
    }


def _as_loss_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, CapabilityLossItem):
        return item.model_dump(mode="json")
    if isinstance(item, BaseModel):
        return item.model_dump(mode="json")
    if isinstance(item, dict):
        return dict(item)
    # generic object with attrs
    out = {}
    for k in ("field_path", "status", "severity", "reason", "source_ref", "target_ref", "remediation", "source_field", "source_path", "detail", "reason_code", "id", "portable_alternative"):
        if hasattr(item, k):
            out[k] = getattr(item, k)
    return out


def _normalize_input_loss(item: Any, *, index: int) -> CapabilityLossItem:
    d = _as_loss_dict(item)
    # map conversion-style loss to export loss schema
    field_path = d.get("field_path")
    if not field_path:
        src = d.get("source_path") or "manifest"
        fld = d.get("source_field") or d.get("field") or f"item_{index}"
        field_path = f"{src}:{fld}" if src != "manifest" else str(fld)
    status = d.get("status")
    severity = d.get("severity")
    reason = d.get("reason") or d.get("detail") or d.get("reason_code") or "capability loss"
    source_ref = d.get("source_ref") or d.get("source_path") or "agent_pack"
    target_ref = d.get("target_ref")
    remediation = d.get("remediation") or d.get("portable_alternative")

    # normalize severity/status from conversion vocabulary
    sev_raw = str(severity or "warn").lower()
    if sev_raw == "high":
        sev = "blocker"
    elif sev_raw in _LOSS_SEVERITIES:
        sev = sev_raw
    else:
        sev = "warn"

    st_raw = str(status or "unsupported").lower()
    if st_raw in _LOSS_STATUSES:
        st = st_raw
    else:
        # conversion had no status; map by reason/severity
        if sev == "blocker":
            st = "unsupported"
        else:
            st = "partial"

    fp = str(field_path)
    # Denied wins rule for reporting: if reason implies denied
    if "denied" in str(reason).lower() or "deny" in str(d.get("reason_code", "")).lower():
        st = "denied"
        sev = "blocker" if sev != "blocker" else sev

    return CapabilityLossItem(
        field_path=fp,
        status=st,  # type: ignore[arg-type]
        severity=sev,  # type: ignore[arg-type]
        reason=str(reason)[:1000],
        source_ref=str(source_ref)[:500],
        target_ref=str(target_ref)[:500] if target_ref is not None else None,
        remediation=str(remediation)[:1000] if remediation is not None else None,
    )


def _dedupe_losses(items: list[CapabilityLossItem]) -> list[CapabilityLossItem]:
    merged: dict[tuple[str, str, str, str, str | None, str | None], CapabilityLossItem] = {}
    for item in items:
        key = (item.field_path, item.status, item.severity, item.reason, item.source_ref, item.target_ref)
        prev = merged.get(key)
        if prev is None:
            merged[key] = item
            continue
        # denied wins / highest severity wins
        st = item.status if _STATUS_RANK[item.status] >= _STATUS_RANK[prev.status] else prev.status
        sev = item.severity if _SEVERITY_RANK[item.severity] >= _SEVERITY_RANK[prev.severity] else prev.severity
        remediation = item.remediation or prev.remediation
        merged[key] = CapabilityLossItem(
            field_path=item.field_path,
            status=st,
            severity=sev,
            reason=item.reason,
            source_ref=item.source_ref,
            target_ref=item.target_ref,
            remediation=remediation,
        )
    # denied wins across same field_path: if any denied, elevate? keep entries but ensure denied present; spec: "Denied wins"
    by_field: dict[str, list[CapabilityLossItem]] = {}
    for it in merged.values():
        by_field.setdefault(it.field_path, []).append(it)
    out: list[CapabilityLossItem] = []
    for fp in sorted(by_field):
        group = by_field[fp]
        if any(g.status == "denied" for g in group):
            # ensure no weaker conflicting status without denied marker; keep denied entries, and downgrade others to denied? safer: mark all as denied blocker if conflicting
            has_denied = [g for g in group if g.status == "denied"]
            for g in group:
                if g.status != "denied":
                    out.append(CapabilityLossItem(
                        field_path=g.field_path,
                        status="denied",
                        severity="blocker",
                        reason=f"Denied wins over {g.status}: {g.reason}",
                        source_ref=g.source_ref,
                        target_ref=g.target_ref,
                        remediation=g.remediation or "Remove denied/unsupported field or provide approved mapping",
                    ))
                else:
                    out.append(CapabilityLossItem(**{**g.model_dump(), "severity": "blocker"}))
        else:
            out.extend(group)
    return sorted(out, key=lambda x: (x.field_path, x.status, x.severity, x.reason, x.source_ref, x.target_ref or ""))


def _target_supported_fields(target: ExportTarget) -> set[str]:
    common = {
        "schema_version", "version", "identity", "identity.id", "identity.name", "identity.agent_type",
        "identity.description", "identity.owner", "identity.tags", "prompt", "prompt.system_prompt",
        "prompt.variables", "prompt.scaffold_required", "tools", "tools.allowed_tools", "tools.denied_tools",
        "tools.risk_classes", "routines", "approvals", "approvals.mode", "approvals.required_for",
        "approvals.approval_ttl_seconds", "approvals.explicit_preapproved_allowed", "memory_scope",
        "changelog", "provenance",
    }
    if target == "claude_code":
        return common | {"runtime_targets"}
    if target == "codex":
        return common | {"runtime_targets"}
    if target == "opencode":
        return common | {"runtime_targets"}
    if target == "openclaw":
        return common | {"runtime_targets"}
    return common


def _build_export_losses(manifest: AgentPackManifest, target: ExportTarget, capability_loss: list[Any] | None) -> list[CapabilityLossItem]:
    items: list[CapabilityLossItem] = []
    for i, raw in enumerate(capability_loss or []):
        items.append(_normalize_input_loss(raw, index=i))

    src = f"agent_pack:{manifest.identity.id}@{manifest.version}"
    tgt = f"{target}:bundle"

    # Required explicit: unsigned
    items.append(CapabilityLossItem(
        field_path="provenance.signature",
        status="unsupported" if not manifest.provenance.signature else "transformed",
        severity="warn",
        reason="Bundle is unsigned; signature not verified or emitted as trusted",
        source_ref=src,
        target_ref=f"{tgt}/provenance.json",
        remediation="Sign bundle out-of-band and verify before install/import",
    ))

    # HITL downgrade blocker if mode none but required_for/side effects suggest otherwise? Spec: "HITL downgrade blocker"
    approvals = manifest.approvals
    side_effect_tools = [t for t, rc in manifest.tools.risk_classes.items() if rc in {"side_effect", "destructive"}]
    if approvals.mode == "none" and (approvals.required_for or side_effect_tools):
        items.append(CapabilityLossItem(
            field_path="approvals.mode",
            status="denied",
            severity="blocker",
            reason="HITL downgrade denied: mode=none with required_for/risky tools",
            source_ref=src,
            target_ref=f"{tgt}/tool-policy.json",
            remediation="Set approvals.mode to ask_tools/policy and keep explicit_preapproved_allowed=false",
        ))

    # runtime targets portability
    if len(manifest.runtime_targets) > 1:
        items.append(CapabilityLossItem(
            field_path="runtime_targets",
            status="partial",
            severity="warn",
            reason="Multiple runtime targets exported as metadata; target runtime may support subset",
            source_ref=src,
            target_ref=f"{tgt}/tool-policy.json",
            remediation="Validate runtime target compatibility in consuming platform",
        ))

    # target-specific notes
    if target == "opencode":
        items.append(CapabilityLossItem(
            field_path="opencode.root_config",
            status="supported",
            severity="info",
            reason="Export emits opencode.agent.fragment.json only; root opencode.json never written",
            source_ref=src,
            target_ref=f"{tgt}/opencode.agent.fragment.json",
            remediation=None,
        ))
    if target == "openclaw":
        items.append(CapabilityLossItem(
            field_path="openclaw.bundle",
            status="partial",
            severity="warn",
            reason="OpenClaw export is conservative; unknown/lossy fields marked and no executable side-effect stubs emitted",
            source_ref=src,
            target_ref=f"{tgt}/openclaw/agent.bundle.json",
            remediation="Review capability-loss report before import",
        ))

    # no executable side-effect stubs
    items.append(CapabilityLossItem(
        field_path="tools.side_effect_stubs",
        status="supported",
        severity="info",
        reason="No executable side-effect stubs emitted",
        source_ref=src,
        target_ref=tgt,
        remediation=None,
    ))

    return _dedupe_losses(items)


def _render_skill_md(manifest: AgentPackManifest) -> str:
    ident = manifest.identity
    desc = ident.description.replace("\n", " ").strip() or ident.name
    frontmatter = {
        "name": ident.id,
        "description": desc[:500],
        "agent_type": ident.agent_type,
        "version": manifest.version,
    }
    fm = "---\n" + "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in frontmatter.items()) + "\n---\n\n"
    body = f"# {ident.name}\n\n{manifest.prompt.system_prompt.rstrip()}\n"
    return fm + body


def _tool_policy(manifest: AgentPackManifest) -> dict[str, Any]:
    return {
        "allowed_tools": list(manifest.tools.allowed_tools),
        "denied_tools": list(manifest.tools.denied_tools),
        "risk_classes": dict(sorted(manifest.tools.risk_classes.items())),
        "approvals": manifest.approvals.model_dump(mode="json"),
    }


def _routines(manifest: AgentPackManifest) -> list[dict[str, Any]]:
    return [r.model_dump(mode="json") for r in sorted(manifest.routines, key=lambda r: r.id)]


def _canonical_pack(manifest: AgentPackManifest) -> dict[str, Any]:
    return manifest.model_dump(mode="json")


def _provenance_payload(manifest: AgentPackManifest, target: ExportTarget, bundle_sha256: str) -> dict[str, Any]:
    return {
        "source_pack_fingerprint": manifest_fingerprint(manifest),
        "source_provenance": manifest.provenance.model_dump(mode="json"),
        "target": target,
        "exporter": "aios.core.agent_pack_export",
        "created_at": manifest.provenance.created_at or _now_iso(),
        "unsigned": True,
        "bundle_sha256": bundle_sha256,
    }


def _bundle_manifest_payload(
    *,
    manifest: AgentPackManifest,
    target: ExportTarget,
    files: list[dict[str, Any]],
    loss_items: list[CapabilityLossItem],
) -> dict[str, Any]:
    files_sorted = sorted(files, key=lambda x: x["path"])
    bundle_sha = _sha256_json([{"path": f["path"], "sha256": f["sha256"], "bytes": f["bytes"]} for f in files_sorted])
    return {
        "schema_version": "1.0.0",
        "target": target,
        "source_pack_fingerprint": manifest_fingerprint(manifest),
        "created_at": manifest.provenance.created_at or _now_iso(),
        "unsigned": True,
        "files": files_sorted,
        "bundle_sha256": bundle_sha,
        "capability_loss_count": len(loss_items),
    }


def _loss_report_payload(
    *,
    manifest: AgentPackManifest,
    target: ExportTarget,
    loss_items: list[CapabilityLossItem],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "target": target,
        "source_pack_fingerprint": manifest_fingerprint(manifest),
        "source_pack_id": manifest.identity.id,
        "source_pack_version": manifest.version,
        "items": [i.model_dump(mode="json") for i in loss_items],
    }


def _render_claude_md(manifest: AgentPackManifest) -> str:
    lines = [
        f"# {manifest.identity.name}",
        "",
        manifest.identity.description.strip(),
        "",
        "## Agent",
        f"- id: {manifest.identity.id}",
        f"- type: {manifest.identity.agent_type}",
        f"- version: {manifest.version}",
        "",
        "## System Prompt",
        manifest.prompt.system_prompt.rstrip(),
        "",
        "## Approvals",
        f"- mode: {manifest.approvals.mode}",
        f"- required_for: {', '.join(manifest.approvals.required_for) or '(none)'}",
        "",
    ]
    return "\n".join(lines).strip() + "\n"


def _render_agents_md(manifest: AgentPackManifest) -> str:
    lines = [
        f"# {manifest.identity.name}",
        "",
        manifest.identity.description.strip(),
        "",
        "## Identity",
        f"- id: {manifest.identity.id}",
        f"- agent_type: {manifest.identity.agent_type}",
        f"- version: {manifest.version}",
        "",
        "## Prompt",
        manifest.prompt.system_prompt.rstrip(),
        "",
        "## Tool Policy",
        f"- allowed_tools: {', '.join(manifest.tools.allowed_tools) or '(none)'}",
        f"- denied_tools: {', '.join(manifest.tools.denied_tools) or '(none)'}",
        "",
    ]
    return "\n".join(lines).strip() + "\n"


def _target_files(manifest: AgentPackManifest, target: ExportTarget) -> dict[str, str]:
    files: dict[str, str] = {}
    skill_id = manifest.identity.id
    if not _SAFE_ID_RE.match(skill_id):
        raise AgentPackValidationError("identity.id unsafe for export path", field="identity.id")
    skill_md = _render_skill_md(manifest)
    tool_policy = _canonical_json(_tool_policy(manifest)) + "\n"
    routines = _canonical_json(_routines(manifest)) + "\n"

    if target == "claude_code":
        files["CLAUDE.md"] = _render_claude_md(manifest)
        files[f".claude/skills/{skill_id}/SKILL.md"] = skill_md
        files["tool-policy.json"] = tool_policy
        files["routines.json"] = routines
    elif target == "codex":
        files["AGENTS.md"] = _render_agents_md(manifest)
        files["codex/agent.json"] = _canonical_json({
            "id": manifest.identity.id,
            "name": manifest.identity.name,
            "agent_type": manifest.identity.agent_type,
            "version": manifest.version,
            "prompt": manifest.prompt.model_dump(mode="json"),
            "approvals": manifest.approvals.model_dump(mode="json"),
            "memory_scope": manifest.memory_scope.model_dump(mode="json"),
            "runtime_targets": [rt.model_dump(mode="json") for rt in manifest.runtime_targets],
        }) + "\n"
        files[f"codex/skills/{skill_id}/SKILL.md"] = skill_md
        files["tool-policy.json"] = tool_policy
    elif target == "opencode":
        files["AGENTS.md"] = _render_agents_md(manifest)
        files[f".opencode/skills/{skill_id}/SKILL.md"] = skill_md
        files["tool-policy.json"] = tool_policy
        files["opencode.agent.fragment.json"] = _canonical_json({
            "agent": {
                manifest.identity.id: {
                    "description": manifest.identity.description,
                    "prompt": manifest.prompt.system_prompt,
                    "tools": {
                        "allowed": list(manifest.tools.allowed_tools),
                        "denied": list(manifest.tools.denied_tools),
                    },
                    "metadata": {
                        "source_pack_fingerprint": manifest_fingerprint(manifest),
                        "version": manifest.version,
                    },
                }
            }
        }) + "\n"
    elif target == "openclaw":
        files["AGENTS.md"] = _render_agents_md(manifest)
        files[f"skills/{skill_id}/SKILL.md"] = skill_md
        files["tool-policy.json"] = tool_policy
        files["openclaw/agent.bundle.json"] = _canonical_json({
            "id": manifest.identity.id,
            "name": manifest.identity.name,
            "version": manifest.version,
            "prompt": manifest.prompt.model_dump(mode="json"),
            "tools": manifest.tools.model_dump(mode="json"),
            "routines": _routines(manifest),
            "approvals": manifest.approvals.model_dump(mode="json"),
            "memory_scope": manifest.memory_scope.model_dump(mode="json"),
            "runtime_targets": [rt.model_dump(mode="json") for rt in manifest.runtime_targets],
            "unsigned": True,
        }) + "\n"
    else:
        raise AgentPackValidationError(f"unknown export target: {target}", field="target")

    return dict(sorted(files.items()))


def export_agent_pack(
    manifest: AgentPackManifest,
    *,
    target: ExportTarget,
    output_dir: str | Path,
    capability_loss: list | None = None,
) -> ExportResult:
    if target not in _TARGETS:
        raise AgentPackValidationError(f"unknown export target: {target}", field="target")
    manifest = validate_agent_pack(manifest)
    out_dir = _ensure_safe_output_dir(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # refuse if output dir itself became symlink in racey sense? check
    if out_dir.is_symlink():
        raise AgentPackValidationError("output_dir must not be a symlink", field="output_dir")

    loss_items = _build_export_losses(manifest, target, capability_loss)

    # write non-manifest files first
    files_meta: list[dict[str, Any]] = []
    target_files = _target_files(manifest, target)
    for rel, content in target_files.items():
        files_meta.append(_write_file(out_dir, rel, content))

    canonical_rel = "agent-pack.canonical.json"
    loss_rel = "capability-loss.report.json"
    provenance_rel = "provenance.json"
    bundle_manifest_rel = "bundle.manifest.json"

    files_meta.append(_write_file(out_dir, canonical_rel, _canonical_json(_canonical_pack(manifest)) + "\n"))
    files_meta.append(_write_file(out_dir, loss_rel, _canonical_json(_loss_report_payload(manifest=manifest, target=target, loss_items=loss_items)) + "\n"))

    # provisional bundle manifest for provenance hash? compute from files excluding provenance and bundle manifest.
    pre_files = sorted(files_meta, key=lambda x: x["path"])
    pre_bundle_sha = _sha256_json([{"path": f["path"], "sha256": f["sha256"], "bytes": f["bytes"]} for f in pre_files])
    prov_payload = _provenance_payload(manifest, target, pre_bundle_sha)
    files_meta.append(_write_file(out_dir, provenance_rel, _canonical_json(prov_payload) + "\n"))

    # final bundle manifest includes all files except itself? include all files including provenance and loss/canonical; manifest lists files and its own hash is excluded by convention? better include all other files and also include manifest itself? can't self-include hash. common: manifest covers files except manifest.
    final_files = sorted(files_meta, key=lambda x: x["path"])
    bundle_manifest_payload = _bundle_manifest_payload(manifest=manifest, target=target, files=final_files, loss_items=loss_items)
    files_meta.append(_write_file(out_dir, bundle_manifest_rel, _canonical_json(bundle_manifest_payload) + "\n"))

    all_files = sorted([f["path"] for f in files_meta])
    # verify all inside output_dir
    for rel in all_files:
        _safe_rel_path(out_dir, rel)

    return ExportResult(
        target=target,
        output_dir=str(out_dir),
        bundle_manifest_path=str(out_dir / bundle_manifest_rel),
        capability_loss_report_path=str(out_dir / loss_rel),
        provenance_path=str(out_dir / provenance_rel),
        files=all_files,
        bundle_sha256=bundle_manifest_payload["bundle_sha256"],
        fingerprint=manifest_fingerprint(manifest),
    )
