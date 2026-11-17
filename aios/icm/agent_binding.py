"""Bind standalone/proactive agent runs to an ICM-X stage contract.

Agents opt in through ``extra_data["icm"]``::

    {"workspace_id": "sales_ops", "stage_id": "sdr_prospecting"}

The manifest is resolved from the org's workspace on disk, so the stage
contract stays a versioned file instead of duplicated agent config.
"""
from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace

from aios.config import settings
from aios.icm.adapter import ICMStageAdapter

logger = logging.getLogger(__name__)


class ICMContractRequired(RuntimeError):
    """A paid workflow class was declared without an enforceable ICM-X contract.

    Opt-in ICM-X remains valid for experiments and internal utilities; the paid
    workflow classes this platform sells must be governed. Failing at startup is
    the point: an agent that would execute a revenue workflow without a stage
    contract must not run.
    """


def assert_paid_workflow_contract(agent) -> None:
    """Raise when ``extra_data["workflow_class"]`` has no bound stage contract."""
    # Imported lazily: the vertical package imports ICM contracts, and the
    # binding module must stay importable while the app is still booting.
    from aios.verticals.pet_business.workflows import has_contract, paid_workflow_class

    workflow_class = paid_workflow_class(getattr(agent, "extra_data", None))
    if not workflow_class:
        return
    if not has_contract(workflow_class):
        raise ICMContractRequired(
            f"workflow_class={workflow_class!r} is not owned by any vertical contract"
        )
    cfg = (getattr(agent, "extra_data", None) or {}).get("icm") or {}
    if not isinstance(cfg, dict) or not (
        cfg.get("stage_id") or cfg.get("stage_manifest")
    ):
        raise ICMContractRequired(
            f"workflow_class={workflow_class!r} requires extra_data['icm'] "
            f"(workspace_id + stage_id)"
        )


def bind_agent_stage(agent, storage_root: str | None = None, run_id: str | None = None):
    """Return the agent's ICM-X adapter, or ``None`` when not opted in."""
    cfg = (agent.extra_data or {}).get("icm") or {}
    if not isinstance(cfg, dict) or not (
        cfg.get("stage_id") or cfg.get("stage_manifest")
    ):
        return None

    node = SimpleNamespace(
        id=cfg.get("stage_id") or "agent_run",
        workspace_id=cfg.get("workspace_id") or "default",
        stage_manifest=cfg.get("stage_manifest"),
        timeout=cfg.get("timeout_seconds") or 3600,
        agent_id=agent.id,
        output_key="icm_input",
        tool_name=None,
    )
    adapter = ICMStageAdapter(
        node,
        storage_root=storage_root or settings.app_data_dir,
        org_id=agent.org_id or "default",
        run_id=run_id or f"agent-{uuid.uuid4().hex[:12]}",
        workspace_id=node.workspace_id,
    )
    # Loads bounded layered context and caps the node timeout to the manifest.
    adapter.pre_execute({}, {"icm_input": ""})
    adapter.timeout_seconds = int(node.timeout)
    logger.info(
        "ICM-X bound agent=%s stage=%s workspace=%s v%s",
        agent.id, adapter.manifest.id, adapter.workspace_id, adapter.manifest.version,
    )
    return adapter
