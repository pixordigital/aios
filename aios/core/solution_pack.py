"""Solution packs: SOLUTIONS entries -> versioned AgentPackManifest (named teams)."""

from typing import Any

from aios.core.agent_pack import (
    AgentPackManifest,
    PackApprovalPolicy,
    PackChangelogEntry,
    PackIdentity,
    PackMemoryScope,
    PackProvenance,
    PackPrompt,
    PackRuntimeTarget,
    PackToolPolicy,
    _checksum_fingerprint,
    validate_agent_pack,
)
from aios.templates import _PROMPT_SCAFFOLD
from aios.templates.solutions import SOLUTIONS, get_solution

SOLUTION_PACK_VERSION = "1.0.0"


def build_solution_pack(key: str, *, created_by: str = "catalog", created_at: str = "2026-11-27") -> AgentPackManifest:
    """Build a versioned AgentPack from a named Solution (e.g. 'vender' -> SDR team)."""
    sol = get_solution(key)
    version = SOLUTION_PACK_VERSION
    addon = str(sol.get("addon") or "")
    scaffolded = addon if "# Camada 1 — Papel e escopo" in addon else addon + _PROMPT_SCAFFOLD
    manifest = AgentPackManifest(
        schema_version="1.0.0",
        version=version,
        identity=PackIdentity(
            id=f"sol-{key}",
            name=str(sol.get("title") or key),
            agent_type=str(sol.get("agent_type") or "sdr"),
            description=str(sol.get("desc") or ""),
            owner=str(sol.get("agent_name") or key),
            tags=[key],
        ),
        prompt=PackPrompt(system_prompt=scaffolded, variables=[], scaffold_required=True),
        tools=PackToolPolicy(allowed_tools=list(sol.get("tools") or []), denied_tools=[], risk_classes={}),
        routines=[],
        approvals=PackApprovalPolicy(mode="ask_tools", required_for=[]),
        memory_scope=PackMemoryScope(scopes=["conversation", "agent"]),
        runtime_targets=[PackRuntimeTarget(target="docker", entrypoint="main:run", image=None, resources={})],
        changelog=[PackChangelogEntry(version=version, date=created_at, summary=f"Solution pack: {sol.get('title')}", author=created_by)],
        provenance=PackProvenance(source=f"solutions:{key}", created_by=created_by, created_at=f"{created_at}T00:00:00Z", checksum_sha256=None, signature=None, parent_fingerprint=None),
    )
    validated = validate_agent_pack(manifest)
    return validated.model_copy(update={"provenance": validated.provenance.model_copy(update={"checksum_sha256": _checksum_fingerprint(validated)})})


def solution_pack_keys() -> list[str]:
    return sorted(SOLUTIONS.keys())


def build_solution_pack_dict(key: str) -> dict[str, Any]:
    m = build_solution_pack(key)
    return {
        "key": key,
        "title": m.identity.name,
        "desc": str(m.identity.description or ""),
        "agent_type": m.identity.agent_type,
        "version": m.version,
        "manifest": m.model_dump(mode="json"),
    }


def _slug(text: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")
    return slug[:63] or "team"


def design_team_pack(
    base_key: str,
    vertical: str,
    addon: str,
    *,
    created_by: str = "designer",
    created_at: str = "2026-11-27",
    runtime_target: str = "docker",
) -> AgentPackManifest:
    """Design a new named team pack by cloning/adapting a base Solution (MVP, deterministic)."""
    base = build_solution_pack(base_key, created_by=created_by, created_at=created_at)
    version = SOLUTION_PACK_VERSION
    slug = _slug(vertical)
    prompt_text = str(base.prompt.system_prompt) + f"\n\n# Escopo do time (projeto: {vertical})\n{addon}"
    manifest = AgentPackManifest(
        schema_version="1.0.0",
        version=version,
        identity=PackIdentity(
            id=f"sol-{base_key}-{slug}",
            name=f"{base.identity.name} — {vertical[:60]}",
            agent_type=base.identity.agent_type,
            description=f"Designed team from {base_key}: {vertical}",
            owner=base.identity.owner,
            tags=[base_key, slug],
        ),
        prompt=PackPrompt(system_prompt=prompt_text, variables=list(base.prompt.variables), scaffold_required=True),
        tools=base.tools,
        routines=[],
        approvals=base.approvals,
        memory_scope=base.memory_scope,
        runtime_targets=[PackRuntimeTarget(target=runtime_target, entrypoint="main:run", image=None, resources={})],  # type: ignore[arg-type]
        changelog=[PackChangelogEntry(version=version, date=created_at, summary=f"Designed team from {base_key}: {vertical}", author=created_by)],
        provenance=PackProvenance(source=f"designs:{base_key}", created_by=created_by, created_at=f"{created_at}T00:00:00Z", checksum_sha256=None, signature=None, parent_fingerprint=None),
    )
    validated = validate_agent_pack(manifest)
    return validated.model_copy(update={"provenance": validated.provenance.model_copy(update={"checksum_sha256": _checksum_fingerprint(validated)})})
