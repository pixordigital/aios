"""ICM-X Stage Adapter for AIOS Workflow Engine.

Connects WorkflowNode execution to machine-enforceable StageManifests,
bounded layered context loading, governance enforcement (allowed/denied tools),
and audit provenance tracking.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from aios.icm.contracts import StageManifest, load_stage_manifest, manifest_fingerprint
from aios.icm.workspace import WorkspacePaths, load_context_files

logger = logging.getLogger(__name__)


class ICMStageAdapter:
    """Adapts an AIOS workflow node to an ICM-X stage manifest."""

    def __init__(
        self,
        node: Any,
        storage_root: str | Path = "data",
        org_id: str = "default",
        run_id: str = "run_default",
        workspace_id: str | None = None,
    ):
        self.node = node
        self.paths = WorkspacePaths(Path(storage_root))
        self.org_id = org_id or "default"
        self.run_id = run_id or "run_default"
        self.workspace_id = (
            workspace_id
            or getattr(node, "workspace_id", None)
            or "b2b_lead_research"
        )
        self.stage_id = getattr(node, "stage_id", None) or getattr(node, "id", "")
        self.manifest: StageManifest = self._resolve_manifest()
        self.context_hashes: dict[str, str] = {}
        self.loaded_context: str = ""

    def _resolve_manifest(self) -> StageManifest:
        manifest_obj = getattr(self.node, "stage_manifest", None)
        if isinstance(manifest_obj, StageManifest):
            return manifest_obj
        if isinstance(manifest_obj, dict):
            return StageManifest.model_validate(manifest_obj)
        if isinstance(manifest_obj, (str, Path)):
            return load_stage_manifest(manifest_obj)

        try:
            stage_dir = self.paths.stage(self.org_id, self.workspace_id, self.stage_id)
            yaml_path = stage_dir / "stage.yaml"
            if yaml_path.is_file():
                return load_stage_manifest(yaml_path)
        except Exception:
            pass

        raise ValueError(
            f"No valid StageManifest found for node '{self.node.id}' (stage_id='{self.stage_id}')"
        )

    def pre_execute(self, ctx: dict, shared: dict) -> None:
        """Validate governance boundaries and load layered context before execution."""
        # 1. Tool Governance validation
        tool_name = getattr(self.node, "tool_name", None)
        if tool_name:
            if self.manifest.denied_tools and tool_name in self.manifest.denied_tools:
                raise PermissionError(
                    f"Tool '{tool_name}' is explicitly denied by stage '{self.manifest.id}'"
                )
            if self.manifest.allowed_tools and tool_name not in self.manifest.allowed_tools:
                raise PermissionError(
                    f"Tool '{tool_name}' is not permitted by stage '{self.manifest.id}' allowlist"
                )

        # 2. Timeout bounds
        if hasattr(self.node, "timeout"):
            self.node.timeout = min(float(self.node.timeout), float(self.manifest.timeout_seconds))

        # 3. Layered Context Loading
        try:
            ws_dir = self.paths.workspace(self.org_id, self.workspace_id)
            if ws_dir.is_dir():
                layer_map: dict[str, list[str]] = {
                    "identity": ["L0/WORKSPACE.md"],
                    "routing": ["L1/ROUTES.md"],
                    "stage": [f"L2/stages/{self.stage_id}/CONTEXT.md"],
                }
                l3_dir = ws_dir / "L3" / "static"
                if l3_dir.is_dir():
                    layer_map["static_references"] = [
                        p.relative_to(ws_dir).as_posix()
                        for p in sorted(l3_dir.glob("*.md"))
                    ]

                allowed_layers = list(self.manifest.context.layers)
                text, hashes = load_context_files(
                    ws_dir,
                    layer_map,
                    allowed_layers=allowed_layers,
                )
                self.loaded_context = text
                self.context_hashes = hashes

                if text:
                    ctx["icm_context"] = text
                    shared["icm_context"] = text
                    # For agent execution, append context instructions to the prompt
                    if getattr(self.node, "agent_id", None):
                        base_msg = shared.get(self.node.output_key) or shared.get("initial_input") or ""
                        if text not in str(base_msg):
                            shared[self.node.output_key] = f"{base_msg}\n\n[ICM Context]:\n{text}".strip()
        except Exception as e:
            logger.debug("ICM-X context loading skipped: %s", e)

    def post_execute(self, output: str, shared: dict) -> dict[str, Any]:
        """Record provenance and persist execution artifacts."""
        fingerprint = manifest_fingerprint(self.manifest)
        provenance = {
            "stage_id": self.manifest.id,
            "version": self.manifest.version,
            "manifest_fingerprint": fingerprint,
            "mode": self.manifest.mode,
            "context_hashes": self.context_hashes,
            "timestamp": time.time(),
        }

        # Save provenance file to disk if run directory can be ensured
        try:
            run_dir = self.paths.ensure_run_directories(self.org_id, self.workspace_id, self.run_id)
            prov_file = run_dir / "provenance" / f"{self.manifest.id}.json"
            prov_file.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
            if output:
                artifact_file = run_dir / "artifacts" / f"{self.manifest.id}_output.txt"
                artifact_file.write_text(str(output), encoding="utf-8")
        except Exception as e:
            logger.debug("Failed saving ICM-X provenance files to disk: %s", e)

        # Store in shared memory for persistence in WorkflowRun.outputs
        if "_icm_provenance" not in shared:
            shared["_icm_provenance"] = {}
        shared["_icm_provenance"][self.node.id] = provenance
        return provenance
