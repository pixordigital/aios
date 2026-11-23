"""Seed internal agent teams for Pixor — idempotent by name.

Teams: sales (sdr+closer), dev (frontend+backend), red, blue.
Each team gets a manager agent (manager_agent_id) + supervisor routing.

Slack wiring (optional): set SLACK_BOT_TOKEN + SLACK_CH_<SALES|DEV|RED|BLUE>
with Slack channel IDs to create one ChannelConnection per team channel.
Without them, teams+agents are created and channels can be wired later
via /dashboard/channels (config key: slack_channel_id).

Usage: python3 scripts/seed_internal_teams.py
Set SLACK_SYNC_APPLY=1 to persist Slack channel links (default dry-run).
"""

import asyncio
import json
import os
import sys
import urllib.request
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from aios.core.secrets import decrypt_channel_config, encrypt_channel_config
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


async def _sync_slack_channels(db, org, bot_token, apply):
    existing = (await db.execute(
        select(ChannelConnection).where(
            ChannelConnection.org_id == org.id,
            ChannelConnection.channel_type == "slack",
        )
    )).scalars().all()

    token = os.environ.get("SLACK_USER_TOKEN", "") or bot_token
    send_token = bot_token
    for c in existing:
        stored = decrypt_channel_config(c.config or {}).get("bot_token", "")
        if stored:
            if not token:
                token = stored
            if not send_token:
                send_token = stored
            if token and send_token:
                break
    if not token:
        print("! SLACK_USER_TOKEN/SLACK_BOT_TOKEN/unlinked bot token unset — Slack channel sync skipped")
        return

    params = {"types": "public_channel,private_channel", "limit": 200, "exclude_archived": "false"}
    channels = []
    while True:
        req = urllib.request.Request(
            "https://slack.com/api/conversations.list?" + urlencode(params),
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        if not data.get("ok"):
            raise RuntimeError(f"conversations.list failed: {data.get('error')}")
        channels.extend(data.get("channels", []))
        cursor = (data.get("response_metadata") or {}).get("next_cursor", "")
        if not cursor:
            break
        params["cursor"] = cursor

    signing_secret = os.environ.get("AIOS_SLACK_SIGNING_SECRET", "")
    by_id = {}
    by_label = {}
    for c in existing:
        cfg = decrypt_channel_config(c.config or {})
        if cfg.get("slack_channel_id"):
            by_id[cfg["slack_channel_id"]] = c
        if c.label:
            by_label[c.label] = c

    for ch in channels:
        cid, name = ch.get("id", ""), ch.get("name", "")
        if not cid or not name:
            continue
        label = f"Slack #{name}"
        conn = by_id.get(cid) or by_label.get(label)
        cfg = decrypt_channel_config(conn.config or {}) if conn else {}
        cfg["slack_channel_id"] = cid
        if send_token:
            cfg["bot_token"] = send_token
        if signing_secret:
            cfg["signing_secret"] = signing_secret
        is_active = not bool(ch.get("is_archived"))
        changed = conn is None or conn.label != label or conn.is_active != is_active or (
            decrypt_channel_config(conn.config or {}) != cfg
        )
        verb = "+" if conn is None else ("~" if changed else "=")
        if not apply:
            print(f"  {verb} {label} -> {cid} (dry-run)")
            continue
        if conn is None:
            db.add(ChannelConnection(
                org_id=org.id, label=label, channel_type="slack",
                config=encrypt_channel_config(cfg), is_active=is_active,
            ))
        else:
            conn.label = label
            conn.is_active = is_active
            conn.config = encrypt_channel_config(cfg)
        print(f"  {verb} {label} -> {cid}")


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
            existing_pairs = {
                (r.team_id, r.agent_id)
                for r in (await db.execute(
                    select(_ta.c.team_id, _ta.c.agent_id).where(_ta.c.team_id == team.id)
                )).all()
            }
            rows = [
                {"team_id": team.id, "agent_id": a.id}
                for a in members + [manager]
                if (team.id, a.id) not in existing_pairs
            ]
            if rows:
                await db.execute(_ta.insert().values(rows))
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

            # Owner DM channel wiring. config.slack_1on1 marks the channel the
            # weekly + monthly reports post to, and the one notify_human sends
            # to. Without it a team gets no owner-facing reports at all.
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

        await _sync_slack_channels(
            db, org, bot_token, os.environ.get("SLACK_SYNC_APPLY") == "1"
        )
        await db.commit()
        print("OK")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
