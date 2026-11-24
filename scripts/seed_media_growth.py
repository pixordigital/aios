"""Idempotent source seed for Phase 1 Media & Growth agents/team.

Default is dry-run. Use --apply to persist.

Usage:
    python3 scripts/seed_media_growth.py --self-check
    python3 scripts/seed_media_growth.py [--org-slug pixor] [--dry-run]
    python3 scripts/seed_media_growth.py --org-slug pixor --apply
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from aios.db.backend import db_session
from aios.db.models import Agent, AgentVersion, Organization, Team, team_agents
from aios.media_growth import PHASE1_ROLES, agent_config


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-slug", default="pixor")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="persist changes")
    mode.add_argument("--dry-run", action="store_true", help="print planned changes only (default)")
    parser.add_argument("--self-check", action="store_true", help="check media_growth source, no DB")
    args = parser.parse_args()

    if args.self_check:
        from aios.media_growth import _self_check

        result = _self_check()
        if result is False:
            print("error: media_growth self-check failed")
            return 1
        print("OK")
        return 0

    apply = args.apply
    async with db_session() as db:
        org = (await db.execute(
            select(Organization).where(Organization.slug == args.org_slug)
        )).scalars().first()
        if not org:
            print(f"error: org {args.org_slug} not found")
            return 1

        roles = list(PHASE1_ROLES)
        agents = {}
        created_agents = 0
        created_versions = 0

        for role in roles:
            agent = (await db.execute(
                select(Agent).where(Agent.org_id == org.id, Agent.name == role)
            )).scalars().first()
            if agent:
                agents[role] = agent
                if not apply:
                    print(f"= agent {role}")
                continue

            if not apply:
                cfg = agent_config(role)
                print(f"+ agent {cfg['name']}")
                continue

            cfg = agent_config(role)
            agent = Agent(
                org_id=org.id,
                name=cfg["name"],
                agent_type=cfg["agent_type"],
                system_prompt=cfg["system_prompt"],
                llm_config=cfg["llm_config"],
                tools=cfg["tools"],
                memory_config=cfg["memory_config"],
                governance_config=cfg["governance_config"],
                extra_data={"media_growth_role": role, "media_growth_phase": 1},
                status=cfg["status"],
            )
            db.add(agent)
            await db.flush()
            db.add(AgentVersion(
                agent_id=agent.id,
                org_id=org.id,
                version=1,
                name=cfg["name"],
                system_prompt=cfg["system_prompt"],
                llm_config=dict(cfg["llm_config"]),
                tools=list(cfg["tools"]),
                memory_config=dict(cfg["memory_config"]),
                governance_config=dict(cfg["governance_config"]),
                agent_type=cfg["agent_type"],
                change_note="initial",
            ))
            agents[role] = agent
            created_agents += 1
            created_versions += 1

        manager = agents.get("Media Manager")
        if not manager:
            print('error: "Media Manager" not in Phase 1 agents')
            return 1

        team = (await db.execute(
            select(Team).where(Team.org_id == org.id, Team.name == "media")
        )).scalars().first()
        created_team = 0
        if not team:
            if not apply:
                print("+ team media")
            else:
                team = Team(org_id=org.id, name="media", routing_strategy="supervisor")
                db.add(team)
                await db.flush()
                created_team = 1
        elif not apply:
            print("= team media")

        existing_pairs = set()
        if team:
            existing_pairs = {
                (row.team_id, row.agent_id)
                for row in (await db.execute(
                    select(team_agents.c.team_id, team_agents.c.agent_id).where(
                        team_agents.c.team_id == team.id
                    )
                )).all()
            }

        if not apply:
            # Dry-run: compare by role names; new agents have no id yet.
            id_to_name = {
                aid: name
                for aid, name in (await db.execute(
                    select(Agent.id, Agent.name).where(Agent.org_id == org.id)
                )).all()
            }
            current_names = {
                id_to_name.get(aid, aid)
                for tid, aid in existing_pairs if team and tid == team.id
            }
            desired_names = set(roles)
            for name in roles:
                verb = "+" if name not in current_names else "="
                print(f"{verb} link {name} -> media")
            for name in sorted(current_names - desired_names):
                print(f"- link {name} -> media")
            return 0

        desired_ids = {a.id for a in agents.values()}
        current_ids = {aid for _, aid in existing_pairs}
        new_rows = [
            {"team_id": team.id, "agent_id": aid}
            for aid in desired_ids - current_ids
        ]
        if new_rows:
            await db.execute(team_agents.insert().values(new_rows))
        stale_ids = current_ids - desired_ids
        if stale_ids:
            await db.execute(team_agents.delete().where(
                team_agents.c.team_id == team.id,
                team_agents.c.agent_id.in_(stale_ids),
            ))

        manager_changed = team.manager_agent_id != manager.id
        team.manager_agent_id = manager.id
        await db.commit()

        print(
            f"agents_created={created_agents} versions_created={created_versions} "
            f"teams_created={created_team} links_added={len(new_rows)} "
            f"links_removed={len(stale_ids)} manager_set={int(manager_changed)}"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
