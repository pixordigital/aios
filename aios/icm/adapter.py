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
from aios.icm.schemas import SchemaValidationError, validate_schema
from aios.icm.workspace import WorkspacePaths, load_context_files

logger = logging.getLogger(__name__)


class SideEffectDuplicateError(RuntimeError):
    """Idempotency key already claimed by another run in the same org."""


class ICMStageAdapter:
    """Adapts an AIOS workflow node to an ICM-X stage manifest."""

    def __init__(
        self,
        node: Any,
        storage_root: str | Path = "data",
        org_id: str = "default",
        run_id: str = "run_default",
        workspace_id: str | None = None,
        preapproved: Any = None,
        db_session: Any | None = None,
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
        self._manifest_from_workspace = False
        self.manifest: StageManifest = self._resolve_manifest()
        self.context_hashes: dict[str, str] = {}
        self.loaded_context: str = ""
        self.input_validated = False
        self.output_validated = False
        self.approval_bound: dict[str, Any] | None = None
        self.side_effect_recorded = False
        self._preapproved = preapproved
        self.db_session = db_session
        from aios.icm.enforcement import StageBudget

        self.budget = StageBudget.from_manifest(self.manifest)

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
                self._manifest_from_workspace = True
                return load_stage_manifest(yaml_path)
        except Exception:
            pass

        raise ValueError(
            f"No valid StageManifest found for node '{self.node.id}' (stage_id='{self.stage_id}')"
        )

    @property
    def requires_approval(self) -> bool:
        return bool(self.manifest.approval_required or self.manifest.side_effects)

    def side_effect_key(self, task_id: str, action: str | None = None) -> str:
        from aios.icm.enforcement import idempotency_key

        act = action or getattr(self.node, "tool_name", None) or self.manifest.id
        return idempotency_key(self.manifest.id, str(task_id), str(act))

    def _applied_keys(self, shared: dict) -> set[str]:
        raw = shared.get("_icm_side_effect_keys")
        if isinstance(raw, list):
            keys = {str(k) for k in raw}
            shared["_icm_side_effect_keys"] = keys
            return keys
        if isinstance(raw, set):
            return {str(k) for k in raw}
        keys: set[str] = set()
        shared["_icm_side_effect_keys"] = keys
        return keys

    def _claim_side_effect(self, key: str, shared: dict) -> None:
        """Claim key durably before the side effect runs.

        No session => legacy in-memory dedupe. With a session, a key from a
        different run fails closed; a same-run retry is recorded as applied.
        """
        session = self.db_session
        if session is None and isinstance(shared, dict):
            session = shared.get("icm_db_session")
        if session is None:
            return

        import inspect

        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError, SQLAlchemyError

        from aios.icm.dedupe_model import ICMSideEffect

        if inspect.iscoroutinefunction(getattr(session, "execute", None)):
            raise RuntimeError("ICM durable side-effect dedupe needs a sync SQLAlchemy Session")

        def find_existing():
            return session.execute(
                select(ICMSideEffect).where(
                    ICMSideEffect.org_id == self.org_id,
                    ICMSideEffect.idempotency_key == key,
                )
            ).scalar_one_or_none()

        try:
            existing = find_existing()
            if existing is not None:
                if str(existing.run_id) != self.run_id:
                    raise SideEffectDuplicateError(
                        f"ICM side effect '{key}' already claimed by run '{existing.run_id}'"
                    )
                self._applied_keys(shared).add(key)
                return
            session.add(
                ICMSideEffect(
                    org_id=self.org_id,
                    idempotency_key=key,
                    stage_id=self.manifest.id,
                    run_id=self.run_id,
                )
            )
            # Durable before the caller performs the external side effect.
            session.commit()
        except SideEffectDuplicateError:
            raise
        except IntegrityError:
            # Concurrent claim won the unique index. Re-read to tell a same-run
            # retry (idempotent) from a different run (fail closed).
            session.rollback()
            existing = find_existing()
            if existing is not None and str(existing.run_id) == self.run_id:
                self._applied_keys(shared).add(key)
                return
            raise SideEffectDuplicateError(
                f"ICM side effect '{key}' already claimed"
            ) from None
        except SQLAlchemyError as exc:
            session.rollback()
            raise RuntimeError("ICM side-effect dedupe store unavailable") from exc

    def validate_input(self, payload: Any) -> None:
        schema_id = self.manifest.inputs_schema
        if not schema_id:
            self.input_validated = True
            return
        try:
            validate_schema(schema_id, payload)
        except SchemaValidationError as e:
            raise ValueError(f"ICM input schema validation failed: {e}") from e
        self.input_validated = True

    def validate_output(self, payload: Any) -> None:
        schema_id = self.manifest.outputs_schema
        if not schema_id:
            self.output_validated = True
            return
        try:
            validate_schema(schema_id, payload)
        except SchemaValidationError as e:
            raise ValueError(f"ICM output schema validation failed: {e}") from e
        self.output_validated = True

    def _explicit_preapproved(self, shared: dict | None = None) -> dict[str, Any] | None:
        """Return deterministic approval from explicit runtime marker, else None.

        Fail-closed: only explicit markers count. Never fabricate founder/human approval.
        """
        candidates = [self._preapproved]
        if isinstance(shared, dict):
            candidates.append(shared.get("icm_preapproved"))
        src = next((c for c in candidates if isinstance(c, dict)), None)
        if not isinstance(src, dict):
            return None
        if src.get("approved") is not True:
            return None
        actions = src.get("actions")
        if actions is not None:
            if not isinstance(actions, list):
                return None
            wanted = {
                str(self.manifest.id),
                str(getattr(self.node, "tool_name", "") or ""),
                str(getattr(self.node, "id", "") or ""),
                "agent_run",
            }
            if not any(str(a) in wanted for a in actions if str(a).strip()):
                return None
        if src.get("stage_id") not in (None, self.manifest.id):
            return None
        if src.get("node_id") not in (None, getattr(self.node, "id", None)):
            return None
        approval_id = src.get("approval_id")
        if not str(approval_id or "").strip():
            return None
        fp = manifest_fingerprint(self.manifest)
        approval_fp = src.get("approved_fingerprint") or src.get("manifest_fingerprint")
        if approval_fp != fp:
            return None
        session = self.db_session
        if session is None and isinstance(shared, dict):
            session = shared.get("icm_db_session")
        import inspect

        if (
            session is None
            or not callable(getattr(session, "execute", None))
            or inspect.iscoroutinefunction(session.execute)
        ):
            return None

        from sqlalchemy import select
        from sqlalchemy.exc import SQLAlchemyError

        from aios.db.models import PendingAction

        try:
            row = session.execute(
                select(PendingAction).where(
                    PendingAction.id == str(approval_id),
                    PendingAction.org_id == self.org_id,
                    PendingAction.status == "approved",
                    PendingAction.decided_by.is_not(None),
                )
            ).scalar_one_or_none()
        except SQLAlchemyError:
            logger.warning("ICM approval lookup unavailable", exc_info=True)
            return None
        if row is None or not str(row.decided_by or "").strip():
            return None
        return {
            "approval_id": str(approval_id),
            "approved_fingerprint": fp,
            "stage_id": self.manifest.id,
            "node_id": getattr(self.node, "id", None),
            "source": "icm_preapproved",
        }

    def check_approval(self, shared: dict) -> None:
        """Fail closed when manifest requires approval for this execution."""
        if not self.requires_approval:
            return
        approval = shared.get("icm_approval")
        if not isinstance(approval, dict):
            approval = self._explicit_preapproved(shared)
            if isinstance(approval, dict):
                shared["icm_approval"] = approval
        if not isinstance(approval, dict):
            raise PermissionError(
                f"Stage '{self.manifest.id}' requires approval before execution"
            )
        fp = manifest_fingerprint(self.manifest)
        approval_fp = approval.get("approved_fingerprint") or approval.get("manifest_fingerprint")
        approval_id = approval.get("approval_id")
        stage_ok = approval.get("stage_id") in (None, self.manifest.id)
        node_ok = approval.get("node_id") in (None, getattr(self.node, "id", None))
        if not approval_id or approval_fp != fp or not stage_ok or not node_ok:
            raise PermissionError(
                f"Stage '{self.manifest.id}' approval missing/invalid for manifest fingerprint"
            )
        self.approval_bound = {
            "approval_id": str(approval_id),
            "approved_fingerprint": fp,
            "stage_id": self.manifest.id,
            "node_id": getattr(self.node, "id", None),
        }
        if approval.get("source"):
            self.approval_bound["source"] = str(approval["source"])

    def pre_execute(self, ctx: dict, shared: dict) -> None:
        """Validate governance boundaries and load layered context before execution."""
        # 1. Tool Governance validation
        tool_name = getattr(self.node, "tool_name", None)
        if tool_name:
            from aios.icm.enforcement import check_tool

            check_tool(self.manifest, tool_name)

        # 2. Timeout bounds
        if hasattr(self.node, "timeout"):
            self.node.timeout = min(float(self.node.timeout), float(self.manifest.timeout_seconds))

        # 3. Layered Context Loading
        declared_layers = list(self.manifest.context.layers)
        unsupported_layers = set(declared_layers) - {"identity", "routing", "stage", "static_references"}
        if unsupported_layers:
            raise ValueError(
                f"ICM unsupported context layers: {', '.join(sorted(unsupported_layers))}"
            )
        ws_dir = self.paths.workspace(self.org_id, self.workspace_id)
        required_layers = list(declared_layers)
        if required_layers and not ws_dir.is_dir():
            if self._manifest_from_workspace:
                raise FileNotFoundError(
                    f"ICM workspace missing for required context layers: {ws_dir}"
                )
            logger.debug("ICM context workspace missing, skipping: %s", ws_dir)
            required_layers = []
        if required_layers and ws_dir.is_dir():
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

            text, hashes = load_context_files(
                ws_dir,
                layer_map,
                allowed_layers=required_layers,
                max_total_chars=self.manifest.context.max_context_tokens * 4,
            )
            self.loaded_context = text
            self.context_hashes = hashes
            if self._manifest_from_workspace and not hashes:
                raise FileNotFoundError(
                    f"ICM required context layers missing/empty for stage '{self.manifest.id}'"
                )

            if text:
                ctx["icm_context"] = text
                shared["icm_context"] = text
                # For agent execution, append context instructions to the prompt
                if getattr(self.node, "agent_id", None):
                    base_msg = shared.get(self.node.output_key) or shared.get("initial_input") or ""
                    if text not in str(base_msg):
                        shared[self.node.output_key] = f"{base_msg}\n\n[ICM Context]:\n{text}".strip()

        # 4. Input schema validation (fail-closed when declared)
        input_payload = shared.get("icm_input")
        if input_payload is None:
            input_payload = shared.get(getattr(self.node, "output_key", ""), shared.get("initial_input"))
        self.validate_input(input_payload)

    def enforce_execution(self, shared: dict, *, action: str | None = None) -> str | None:
        """Enforce approval/idempotency gates before side-effecting execution.

        Returns idempotency key when stage has side effects, else None.
        """
        self.check_approval(shared)
        if not self.manifest.side_effects:
            return None
        from aios.icm.enforcement import side_effect_already_applied

        task_id = (
            shared.get("task_id")
            or shared.get("run_id")
            or shared.get("conversation_id")
            or self.run_id
        )
        key = self.side_effect_key(str(task_id), action=action)
        self._claim_side_effect(key, shared)
        applied = self._applied_keys(shared)
        if side_effect_already_applied(applied, key):
            self.side_effect_recorded = True
            return key
        applied.add(key)
        self.side_effect_recorded = True
        return key

    def charge_llm(self, cost_usd: float = 0.0) -> None:
        """Record one paid call or raise BudgetExceeded before the provider is hit."""
        self.budget.charge(cost_usd)

    def post_execute(self, output: str, shared: dict) -> dict[str, Any]:
        """Record provenance and persist execution artifacts."""
        self.validate_output(output)
        fingerprint = manifest_fingerprint(self.manifest)
        provenance = {
            "stage_id": self.manifest.id,
            "version": self.manifest.version,
            "manifest_fingerprint": fingerprint,
            "mode": self.manifest.mode,
            "context_hashes": self.context_hashes,
            "llm_calls": self.budget.calls,
            "cost_usd": self.budget.cost_usd,
            "tool_calls": self.budget.tool_calls,
            "input_validated": self.input_validated,
            "output_validated": self.output_validated,
            "side_effects": self.manifest.side_effects,
            "approval_required": self.requires_approval,
            "approval_id": (self.approval_bound or {}).get("approval_id"),
            "approved_fingerprint": (self.approval_bound or {}).get("approved_fingerprint"),
            "side_effect_recorded": self.side_effect_recorded,
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
            provenance["disk_write_error"] = str(e)
            logger.warning("Failed saving ICM-X provenance files to disk: %s", e)

        # Store in shared memory for persistence in WorkflowRun.outputs
        if "_icm_provenance" not in shared:
            shared["_icm_provenance"] = {}
        shared["_icm_provenance"][self.node.id] = provenance
        return provenance
