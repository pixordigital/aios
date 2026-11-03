"""Machine-enforceable ICM-X stage contracts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_MANIFEST_BYTES = 64 * 1024


class ContextPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    layers: list[Literal[
        "identity", "routing", "stage", "static_references",
        "dynamic_references", "run_artifacts",
    ]] = Field(default_factory=lambda: ["identity", "stage", "static_references"])
    max_context_tokens: int = Field(default=6000, ge=256, le=100_000)


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_attempts: int = Field(default=1, ge=1, le=5)
    retry_on: list[str] = Field(default_factory=lambda: ["timeout", "transient_provider_error"])
    no_retry_on: list[str] = Field(default_factory=lambda: ["permission_denied", "invalid_input"])


class StageManifest(BaseModel):
    """Validated, versioned contract for one independently executable stage."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str = Field(default="", max_length=1000)
    mode: Literal["deterministic", "llm", "hybrid"] = "hybrid"
    timeout_seconds: int = Field(default=60, ge=1, le=3600)
    max_llm_calls: int = Field(default=0, ge=0, le=50)
    max_cost_usd: float = Field(default=0.0, ge=0.0, le=100.0)
    inputs_schema: str = Field(default="", max_length=255)
    outputs_schema: str = Field(default="", max_length=255)
    context: ContextPolicy = Field(default_factory=ContextPolicy)
    allowed_tools: list[str] = Field(default_factory=list, max_length=100)
    denied_tools: list[str] = Field(default_factory=list, max_length=100)
    side_effects: bool = False
    approval_required: bool = False
    retry: RetryPolicy = Field(default_factory=RetryPolicy)

    @model_validator(mode="after")
    def validate_execution_budget(self) -> "StageManifest":
        overlap = set(self.allowed_tools) & set(self.denied_tools)
        if overlap:
            raise ValueError(f"tools cannot be both allowed and denied: {sorted(overlap)}")
        if self.mode == "deterministic" and self.max_llm_calls:
            raise ValueError("deterministic stages must set max_llm_calls=0")
        if self.mode == "llm" and self.max_llm_calls == 0:
            raise ValueError("llm stages must declare max_llm_calls > 0")
        if self.max_llm_calls == 0 and self.max_cost_usd > 0:
            raise ValueError("max_cost_usd must be 0 when no LLM calls are allowed")
        return self


def load_stage_manifest(path: str | Path) -> StageManifest:
    """Load a bounded YAML manifest using safe parsing and strict validation."""
    raw = Path(path).read_bytes()
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError(f"stage manifest exceeds {MAX_MANIFEST_BYTES} bytes")
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid stage YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("stage manifest must contain a YAML mapping")
    return StageManifest.model_validate(data)


def manifest_fingerprint(manifest: StageManifest) -> str:
    """Stable SHA-256 for cache keys and provenance; excludes runtime state."""
    payload = json.dumps(
        manifest.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
