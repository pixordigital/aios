#!/usr/bin/env python3
"""Remediate missing tools and prompt discrepancies across AIOS agent fleet.

Updates Agent.tools in the database and cleans up tool references in system prompts.
Can run locally or inside the app container:

    python scripts/remediate_agent_tools.py [--dry-run] [--org-id <uuid>]
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from aios.db.backend import db_session
from aios.db.models import Agent

TOOL_ADDITIONS: dict[str, list[str]] = {
    "sales-sdr": [
        "cal_booking",
        "ask_team_manager",
        "notify_human",
        "calculator",
        "whatsapp_template",
    ],
    "sales-closer": [
        "lead_score",
        "ask_team_manager",
        "notify_human",
        "cal_booking",
        "web_search",
    ],
    "sales-manager": [
        "crm_pipeline_stats",
        "cal_booking",
    ],
    "dev-frontend": [
        "ask_team_manager",
        "notify_human",
    ],
    "dev-backend": [
        "ask_team_manager",
        "notify_human",
        "request_build",
    ],
    "dev-manager": [
        "request_build",
    ],
    "red-agent": [
        "ask_team_manager",
        "notify_human",
        "rag_search",
    ],
    "blue-agent": [
        "ask_team_manager",
        "notify_human",
    ],
    "security-manager": [
        "proactive_alerts",
    ],
    "Data Analyst": [
        "ask_team_manager",
        "notify_human",
    ],
    "Data Scientist": [
        "ask_team_manager",
        "notify_human",
        "transcribe",
    ],
    "data-manager": [
        "proactive_alerts",
    ],
}


def clean_system_prompt(agent_name: str, prompt: str) -> tuple[str, bool]:
    changed = False
    new_prompt = prompt
    if agent_name == "sales-sdr":
        if "knowledge/web_search" in new_prompt:
            new_prompt = new_prompt.replace("knowledge/web_search", "rag_search/web_search")
            changed = True
        if "`knowledge`/`web_search`" in new_prompt:
            new_prompt = new_prompt.replace("`knowledge`/`web_search`", "`rag_search`/`web_search`")
            changed = True
    elif agent_name == "Data Analyst":
        if "(salve via storage_save)" in new_prompt:
            new_prompt = new_prompt.replace(
                "(salve via storage_save)",
                "(salve no sandbox ou retorne em base64)",
            )
            changed = True
    return new_prompt, changed


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print changes without committing")
    parser.add_argument("--org-id", default=None, help="Scope changes to a specific org")
    args = parser.parse_args()

    async with db_session() as db:
        stmt = select(Agent)
        if args.org_id:
            stmt = stmt.where(Agent.org_id == args.org_id)
        agents = (await db.execute(stmt)).scalars().all()

        if not agents:
            print("No agents found matching criteria.")
            return 0

        updated_count = 0
        for agent in agents:
            if agent.status == "archived":
                continue

            additions = TOOL_ADDITIONS.get(agent.name, [])
            current_tools = list(agent.tools or [])
            missing_tools = [t for t in additions if t not in current_tools]

            new_prompt, prompt_changed = clean_system_prompt(agent.name, agent.system_prompt or "")

            if not missing_tools and not prompt_changed:
                print(f"[OK] {agent.name}: tools up to date ({len(current_tools)} tools)")
                continue

            new_tools = sorted(list(set(current_tools + missing_tools)))
            print(f"[UPDATE] {agent.name} (id={agent.id}):")
            if missing_tools:
                print(f"  + Added tools ({len(missing_tools)}): {missing_tools}")
                print(f"  Total tools: {len(current_tools)} -> {len(new_tools)}")
            if prompt_changed:
                print("  + System prompt cleaned (removed obsolete tool references)")

            if not args.dry_run:
                agent.tools = new_tools
                if prompt_changed:
                    agent.system_prompt = new_prompt

            updated_count += 1

        if not args.dry_run and updated_count > 0:
            await db.commit()
            print(f"\nSuccessfully committed changes for {updated_count} agents.")
        else:
            print(f"\nDry-run completed. {updated_count} agents would be updated.")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
