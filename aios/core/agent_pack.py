"""Agent Pack manifest contract (v1).

Fail-closed: any parse/validation/size error raises AgentPackValidationError.
Denied wins: tools in denied_tools must never be allowed; callers should treat
denied_tools as authoritative over allowed_tools and never fabricate approval.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency
    yaml = None  # type: ignore[assignment]

PACK_SCHEMA_VERSION = "1.0.0"
MAX_PACK_BYTES = 128 * 1024

RuntimeTarget = Literal["local_proc", "docker", "k8s", "wasm", "remote_http"]
ApprovalMode = Literal["none", "ask_tools", "ask_all", "policy"]
MemoryScopeKind = Literal["conversation", "agent", "team", "org"]
RiskClass = Literal["read", "write", "side_effect", "destructive"]

_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_STAGE_REF_RE = re.compile(r"^[a-zA-Z0-9_./:-]{1,255}$")


class AgentPackValidationError(ValueError):
    """Raised when an agent pack is missing, malformed, oversized, or unsafe."""

    def __init__(self, message: str, *, field: str | None = None):
        self.field = field
        super().__init__(f"{field}: {message}" if field else message)


class _FrozenPackModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PackIdentity(_FrozenPackModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str = Field(min_length=1, max_length=120)
    agent_type: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=2000)
    owner: str = Field(default="", max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=32)


class PackPrompt(_FrozenPackModel):
    system_prompt: str = Field(min_length=1, max_length=40000)
    variables: list[str] = Field(default_factory=list, max_length=64)
    scaffold_required: bool = True


class PackToolPolicy(_FrozenPackModel):
    allowed_tools: list[str] = Field(default_factory=list, max_length=128)
    denied_tools: list[str] = Field(default_factory=list, max_length=128)
    risk_classes: dict[str, RiskClass] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _no_overlap(self) -> "PackToolPolicy":
        overlap = set(self.allowed_tools) & set(self.denied_tools)
        if overlap:
            raise ValueError(f"allowed_tools and denied_tools overlap: {sorted(overlap)}")
        return self


class PackRoutine(_FrozenPackModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    trigger: str = Field(min_length=1, max_length=120)
    workflow_id: str | None = None
    stage_ref: str | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _stage_ref_format(self) -> "PackRoutine":
        if self.stage_ref is not None and not _STAGE_REF_RE.match(self.stage_ref):
            raise ValueError("stage_ref must match ^[a-zA-Z0-9_./:-]{1,255}$")
        return self


class PackApprovalPolicy(_FrozenPackModel):
    mode: ApprovalMode = "ask_tools"
    required_for: list[str] = Field(default_factory=list, max_length=128)
    approval_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    explicit_preapproved_allowed: bool = False

    @model_validator(mode="after")
    def _no_unsafe_preapproval(self) -> "PackApprovalPolicy":
        if self.mode == "none" and self.explicit_preapproved_allowed:
            raise ValueError("mode='none' with explicit_preapproved_allowed=true is unsafe")
        return self


class PackMemoryScope(_FrozenPackModel):
    scopes: list[MemoryScopeKind] = Field(default_factory=lambda: ["conversation", "agent"])
    max_short_term_messages: int = Field(default=100, ge=1, le=2000)
    long_term_enabled: bool = True
    episodic_enabled: bool = True
    redact_patterns: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def _scopes_non_empty(self) -> "PackMemoryScope":
        if not self.scopes:
            raise ValueError("scopes must be non-empty")
        return self


class PackRuntimeTarget(_FrozenPackModel):
    target: RuntimeTarget
    entrypoint: str = Field(default="", max_length=255)
    image: str | None = Field(default=None, max_length=255)
    resources: dict[str, Any] = Field(default_factory=dict)


class PackChangelogEntry(_FrozenPackModel):
    version: str = Field(pattern=_SEMVER_RE.pattern)
    date: str = Field(pattern=_DATE_RE.pattern)
    summary: str = Field(min_length=1, max_length=500)
    author: str = Field(default="", max_length=120)


class PackProvenance(_FrozenPackModel):
    source: str = Field(min_length=1, max_length=255)
    created_by: str = Field(min_length=1, max_length=120)
    created_at: str = Field(min_length=1, max_length=64)
    checksum_sha256: str | None = Field(default=None, pattern=_SHA256_RE.pattern)
    signature: str | None = Field(default=None, max_length=4096)
    parent_fingerprint: str | None = Field(default=None, pattern=_SHA256_RE.pattern)


class AgentPackManifest(_FrozenPackModel):
    schema_version: str = Field(default=PACK_SCHEMA_VERSION, pattern=_SEMVER_RE.pattern)
    version: str = Field(pattern=_SEMVER_RE.pattern)
    identity: PackIdentity
    prompt: PackPrompt
    tools: PackToolPolicy
    routines: list[PackRoutine] = Field(default_factory=list, max_length=64)
    approvals: PackApprovalPolicy = Field(default_factory=PackApprovalPolicy)
    memory_scope: PackMemoryScope = Field(default_factory=PackMemoryScope)
    runtime_targets: list[PackRuntimeTarget] = Field(min_length=1, max_length=8)
    changelog: list[PackChangelogEntry] = Field(default_factory=list, max_length=100)
    provenance: PackProvenance

    @model_validator(mode="after")
    def _validate_invariants(self) -> "AgentPackManifest":
        routine_ids = [r.id for r in self.routines]
        if len(routine_ids) != len(set(routine_ids)):
            seen: set[str] = set()
            dupes: list[str] = []
            for rid in routine_ids:
                if rid in seen and rid not in dupes:
                    dupes.append(rid)
                seen.add(rid)
            raise ValueError(f"duplicate routine ids: {dupes}")

        if self.changelog and self.changelog[-1].version != self.version:
            raise ValueError(
                "changelog latest entry version must equal manifest.version "
                f"({self.changelog[-1].version!r} != {self.version!r})"
            )

        rt_keys = [(rt.target, rt.entrypoint, rt.image) for rt in self.runtime_targets]
        if len(rt_keys) != len(set(rt_keys)):
            raise ValueError("runtime_targets must be unique by (target, entrypoint, image)")

        checksum = self.provenance.checksum_sha256
        if checksum is not None:
            expected = _checksum_fingerprint(self)
            if checksum != expected:
                raise ValueError(
                    "provenance.checksum_sha256 mismatch: "
                    f"expected {expected}, got {checksum}"
                )
        return self


def _canonical_payload(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _checksum_fingerprint(manifest: AgentPackManifest) -> str:
    """Fingerprint for checksum verification.

    Computed over canonical manifest payload with provenance.checksum_sha256 and
    provenance.signature set to None, so checksum covers content/provenance metadata
    but not the checksum/signature envelope itself.
    """
    data = manifest.model_dump(mode="json")
    prov = data.get("provenance")
    if isinstance(prov, dict):
        prov["checksum_sha256"] = None
        prov["signature"] = None
    return hashlib.sha256(_canonical_payload(data).encode("utf-8")).hexdigest()


def manifest_fingerprint(manifest: AgentPackManifest) -> str:
    """Stable SHA-256 of canonical manifest JSON."""
    payload = _canonical_payload(manifest.model_dump(mode="json")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _parse_pack_bytes(raw: bytes, *, source: str) -> dict[str, Any]:
    if len(raw) > MAX_PACK_BYTES:
        raise AgentPackValidationError(f"pack exceeds {MAX_PACK_BYTES} bytes", field=source)
    text = raw.decode("utf-8")
    # Try JSON first for .json or ambiguous; YAML safe_load handles JSON too, but
    # we prefer explicit JSON errors for .json.
    stripped = text.lstrip()
    try:
        if stripped.startswith("{") or stripped.startswith("["):
            data = json.loads(text)
        else:
            if yaml is None:
                raise AgentPackValidationError("YAML support unavailable", field=source)
            data = yaml.safe_load(text)
    except AgentPackValidationError:
        raise
    except Exception as exc:
        raise AgentPackValidationError(f"invalid pack content: {exc}", field=source) from exc
    if not isinstance(data, dict):
        raise AgentPackValidationError("pack must be a mapping/object", field=source)
    return data


def load_agent_pack(path: str | Path) -> AgentPackManifest:
    """Load, size-check, parse, and strictly validate an agent pack file."""
    p = Path(path)
    source = str(p)
    try:
        raw = p.read_bytes()
    except Exception as exc:
        raise AgentPackValidationError(f"cannot read pack: {exc}", field=source) from exc

    suffix = p.suffix.lower()
    if suffix == ".json":
        if len(raw) > MAX_PACK_BYTES:
            raise AgentPackValidationError(f"pack exceeds {MAX_PACK_BYTES} bytes", field=source)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise AgentPackValidationError(f"invalid JSON: {exc}", field=source) from exc
    elif suffix in {".yaml", ".yml"}:
        if len(raw) > MAX_PACK_BYTES:
            raise AgentPackValidationError(f"pack exceeds {MAX_PACK_BYTES} bytes", field=source)
        if yaml is None:
            raise AgentPackValidationError("YAML support unavailable", field=source)
        try:
            data = yaml.safe_load(raw.decode("utf-8"))
        except Exception as exc:
            raise AgentPackValidationError(f"invalid YAML: {exc}", field=source) from exc
    else:
        data = _parse_pack_bytes(raw, source=source)

    if not isinstance(data, dict):
        raise AgentPackValidationError("pack must be a mapping/object", field=source)

    try:
        return AgentPackManifest.model_validate(data)
    except ValidationError as exc:
        raise AgentPackValidationError(str(exc), field=source) from exc
    except ValueError as exc:
        raise AgentPackValidationError(str(exc), field=source) from exc


def validate_agent_pack(obj: dict[str, Any] | str | Path | AgentPackManifest) -> AgentPackManifest:
    """Validate an in-memory object, manifest, or pack file path."""
    if isinstance(obj, AgentPackManifest):
        return obj
    if isinstance(obj, (str, Path)):
        p = Path(obj)
        if p.exists() or p.suffix.lower() in {".json", ".yaml", ".yml"}:
            return load_agent_pack(p)
        # treat raw string as not-a-file unlikely; but be safe: try as path
        return load_agent_pack(p)
    if not isinstance(obj, dict):
        raise AgentPackValidationError("pack must be a mapping/object")
    try:
        return AgentPackManifest.model_validate(obj)
    except ValidationError as exc:
        raise AgentPackValidationError(str(exc)) from exc
    except ValueError as exc:
        raise AgentPackValidationError(str(exc)) from exc


def pack_counts(manifest: dict[str, Any] | None) -> dict[str, Any]:
    """Derive human-facing catalog counts from an AgentPack manifest.

    Used by the dashboard vitrine: routines, approval policy, runtime targets and
    memory scopes of the active version, without loading the full ORM graph.
    """
    m = manifest or {}
    routines = m.get("routines") or []
    approvals = m.get("approvals") or {}
    memory = m.get("memory_scope") or {}
    runtime_targets = m.get("runtime_targets") or []
    return {
        "routines": len(routines) if isinstance(routines, list) else 0,
        "approval_mode": approvals.get("mode") or "ask_tools",
        "approval_required": len(approvals.get("required_for") or []),
        "runtime_targets": len(runtime_targets) if isinstance(runtime_targets, list) else 0,
        "memory_scopes": len(memory.get("scopes") or []),
        "memory_long_term": bool(memory.get("long_term_enabled")),
    }
