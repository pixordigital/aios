"""Seed internal agent teams for Pixor — idempotent by name.

Teams: sales (sdr+closer), dev (frontend+backend), red, blue.
Each team gets a manager agent (manager_agent_id) + supervisor routing.

Slack wiring (optional): set SLACK_BOT_TOKEN + SLACK_CH_<SALES|DEV|RED|BLUE>
with Slack channel IDs to create one ChannelConnection per team channel.
Without them, teams+agents are created and channels can be wired later
via /dashboard/channels (config key: slack_channel_id).

Usage: python3 scripts/seed_internal_teams.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from aios.db.backend import db_session
from aios.db.models import Agent, ChannelConnection, Organization, Team
from aios.templates import apply_template

TEAMS = {
    # team: (member agent_types, slack env var for channel id)
    "sales": (["sdr", "closer"], "SLACK_CH_SALES"),
    "dev": (["frontend", "backend"], "SLACK_CH_DEV"),
    "red": (["red"], "SLACK_CH_RED"),
    "blue": (["blue"], "SLACK_CH_BLUE"),
}


async def _get_or_create_agent(db, org_id, name, agent_type):
    existing = (await db.execute(
        select(Agent).where(Agent.org_id == org_id, Agent.name == name)
    )).scalars().first()
    if existing:
        return existing, False
    tpl = apply_template(agent_type)
    agent = Agent(
        org_id=org_id,
        name=name,
        agent_type=agent_type,
        system_prompt=tpl.get("system_prompt", ""),
        llm_config=tpl.get("llm_config", {}),
        tools=tpl.get("tools", []),
        memory_config=tpl.get("memory_config", {}),
        status="active",
    )
    db.add(agent)
    await db.flush()
    return agent, True


async def main():
    async with db_session() as db:
        org = (await db.execute(
            select(Organization).where(Organization.slug == "pixor")
        )).scalars().first()
        if not org:
            org = Organization(name="Pixor", slug="pixor", extra_data={"plan": "unlimited"})
            db.add(org)
            await db.flush()  # before_flush hook pins plan=unlimited
            print("+ org pixor")

        bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
        for team_name, (member_types, ch_env) in TEAMS.items():
            team = (await db.execute(
                select(Team).where(Team.org_id == org.id, Team.name == team_name)
            )).scalars().first()
            if not team:
                team = Team(org_id=org.id, name=team_name, routing_strategy="supervisor")
                db.add(team)
                await db.flush()
                print(f"+ team {team_name}")
            else:
                print(f"= team {team_name} exists")

            members = []
            for atype in member_types:
                # team "red" + type "red" would otherwise produce "red-red"
                agent_name = f"{team_name}-{atype}" if team_name != atype else f"{atype}-agent"
                agent, created = await _get_or_create_agent(db, org.id, agent_name, atype)
                members.append(agent)
                print(f"  {'+' if created else '='} agent {agent.name}")
            manager, created = await _get_or_create_agent(db, org.id, f"{team_name}-manager", "manager")
            print(f"  {'+' if created else '='} agent {manager.name} (manager)")

            from aios.db.models import team_agents as _ta
            await db.execute(_ta.insert().values(
                [{"team_id": team.id, "agent_id": a.id} for a in members + [manager]]
            ))
            team.manager_agent_id = manager.id
            await db.flush()

            # Slack channel wiring
            channel_id = os.environ.get(ch_env, "")
            if channel_id:
                label = f"Slack #{team_name}"
                conn = (await db.execute(
                    select(ChannelConnection).where(
                        ChannelConnection.org_id == org.id,
                        ChannelConnection.label == label,
                    )
                )).scalars().first()
                if not conn:
                    conn = ChannelConnection(
                        org_id=org.id,
                        label=label,
                        channel_type="slack",
                        config={"bot_token": bot_token, "slack_channel_id": channel_id},
                        team_id=team.id,
                        is_active=True,
                    )
                    db.add(conn)
                    print(f"  + channel {label} -> {channel_id}")
                else:
                    conn.team_id = team.id
                    conn.config = {"bot_token": bot_token, "slack_channel_id": channel_id}
                    print(f"  = channel {label} updated")
            else:
                print(f"  ! {ch_env} unset — wire #{team_name} later via dashboard (slack_channel_id)")

            # 1:1 DM channel wiring (biweekly job posts here when config.slack_1on1)
            one_env = f"SLACK_CH_1ON1_{team_name.upper()}"
            one_id = os.environ.get(one_env, "")
            if one_id:
                label = f"Slack 1:1 {team_name}"
                conn = (await db.execute(
                    select(ChannelConnection).where(
                        ChannelConnection.org_id == org.id,
                        ChannelConnection.label == label,
                    )
                )).scalars().first()
                cfg = {"bot_token": bot_token, "slack_channel_id": one_id, "slack_1on1": True}
                if not conn:
                    db.add(ChannelConnection(
                        org_id=org.id, label=label, channel_type="slack",
                        config=cfg, team_id=team.id, is_active=True,
                    ))
                    print(f"  + channel {label} -> {one_id}")
                else:
                    conn.team_id = team.id
                    conn.config = cfg
                    print(f"  = channel {label} updated")

        await db.commit()
        print("OK")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
