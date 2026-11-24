#!/usr/bin/env python3
"""Provision ICM-X team workspaces and bind the org's agents to stages.

Idempotent: seeds the versioned workspaces from ``aios.icm.team_workspaces``,
then writes each agent's stage binding, event subscriptions and explicit
autonomy policy. Run inside the app container after a deploy:

    docker exec <app-container> python scripts/provision_icm_fleet.py \
        --org-id <org-uuid>

Safe to rerun; it only touches the listed agents in the given org.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from aios.config import settings
from aios.db.backend import db_session
from aios.db.models import Agent
from aios.icm.contracts import load_stage_manifest, manifest_fingerprint
from aios.icm.team_workspaces import (
    AGENT_EVENTS,
    AGENT_STAGES,
    TEAM_WORKSPACES,
    seed_team_workspaces,
)

AUTONOMY_POLICY = {
    "autonomy": "autonomous",
    "autonomous": True,
    "hitl_enabled": True,
    "max_trials": 3,
}


def _load_approvals(path: str | None) -> dict:
    """Read explicit approvals; no file means no approvals, never inferred ones."""
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("approvals file must be a JSON object")
    return data


def _approval_marker(entry, stage_id: str, fingerprint: str) -> dict | None:
    """Build a marker only from explicit, fingerprint-matched approval data."""
    if not isinstance(entry, dict) or entry.get("approved_fingerprint") != fingerprint:
        return None
    approval_id = entry.get("approval_id")
    approved_by = entry.get("approved_by")
    actions = entry.get("actions")
    if not str(approval_id or "").strip() or not str(approved_by or "").strip():
        return None
    if not isinstance(actions, list):
        return None
    clean_actions = [str(a) for a in actions if str(a).strip()]
    if not clean_actions:
        return None
    return {
        "approved": True,
        "approval_id": str(approval_id),
        "approved_fingerprint": fingerprint,
        "actions": clean_actions,
        "approved_by": str(approved_by),
        "stage_id": stage_id,
    }


def _agent_extra(
    agent,
    workspace_id: str,
    stage_id: str,
    approvals: dict | None = None,
    fingerprint: str | None = None,
) -> dict:
    """Build the agent's extra_data. Rerunning converges on this exact shape."""
    extra = dict(agent.extra_data or {})
    icm = {"workspace_id": workspace_id, "stage_id": stage_id}
    if approvals and fingerprint:
        marker = _approval_marker(approvals.get(agent.name), stage_id, fingerprint)
        if marker is not None:
            icm["preapproved"] = marker
    extra["icm"] = icm
    if agent.name in AGENT_EVENTS:
        extra["event_subscriptions"] = AGENT_EVENTS[agent.name]
    else:
        extra.pop("event_subscriptions", None)
    return extra


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--storage-root", default=settings.app_data_dir)
    parser.add_argument(
        "--approvals-file",
        help="JSON mapping agent name -> approval_id/approved_fingerprint/actions/approved_by",
    )
    args = parser.parse_args()
    approvals = _load_approvals(args.approvals_file)
    manifests = {}

    if not args.dry_run:
        written = seed_team_workspaces(args.storage_root, args.org_id)
        print(f"seeded {len(written)} workspaces under {args.storage_root}")
        for workspace in written:
            for stage_yaml in workspace.glob("L2/stages/*/stage.yaml"):
                manifest = load_stage_manifest(stage_yaml)
                manifests[(workspace.name, manifest.id)] = manifest
        print(f"validated {len(TEAM_WORKSPACES)} workspaces")

    async with db_session() as db:
        agents = (
            await db.execute(select(Agent).where(Agent.org_id == args.org_id))
        ).scalars().all()
        changed = 0
        for agent in agents:
            binding = AGENT_STAGES.get(agent.name)
            if binding is None:
                continue
            workspace_id, stage_id = binding
            if args.dry_run:
                print(f"would bind {agent.name} -> {workspace_id}/{stage_id}")
                continue
            manifest = manifests.get((workspace_id, stage_id))
            fingerprint = manifest_fingerprint(manifest) if manifest else None
            agent.extra_data = _agent_extra(
                agent, workspace_id, stage_id, approvals, fingerprint
            )
            governance = dict(agent.governance_config or {})
            governance.update(AUTONOMY_POLICY)
            agent.governance_config = governance
            changed += 1
            print(f"bound {agent.name} -> {workspace_id}/{stage_id}")
        if not args.dry_run:
            await db.commit()
        print(f"agents updated: {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
