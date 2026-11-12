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
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from aios.config import settings
from aios.db.backend import db_session
from aios.db.models import Agent
from aios.icm.contracts import load_stage_manifest
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


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--storage-root", default=settings.app_data_dir)
    args = parser.parse_args()

    if not args.dry_run:
        written = seed_team_workspaces(args.storage_root, args.org_id)
        print(f"seeded {len(written)} workspaces under {args.storage_root}")
        for workspace in written:
            for stage_yaml in workspace.glob("L2/stages/*/stage.yaml"):
                load_stage_manifest(stage_yaml)
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
            extra = dict(agent.extra_data or {})
            extra["icm"] = {"workspace_id": workspace_id, "stage_id": stage_id}
            if agent.name in AGENT_EVENTS:
                extra["event_subscriptions"] = AGENT_EVENTS[agent.name]
            agent.extra_data = extra
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
