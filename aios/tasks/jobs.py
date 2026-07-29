"""Async job definitions for ARQ worker.

Each top-level function is a job ARQ can execute.
Registered in FUNCTIONS list for the worker to discover.
"""

import json
import logging

from aios.core.delivery import deliver_message

logger = logging.getLogger(__name__)


async def process_inbound(
    ctx,
    channel_type: str,
    channel_connection_id: str,
    conversation_id: str,
    text: str,
    user_id: str = "",
    extra_data: str = "{}",
):
    """Process an inbound message from any channel.

    Runs in ARQ worker: finds agent, runs it, sends reply via channel.
    """
    from aios.db.backend import db_session
    from aios.db.models import Agent, ChannelConnection, Conversation, Message, Team
    from aios.core.limits import check_org_limits, track_usage
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    try:
        extra = json.loads(extra_data) if isinstance(extra_data, str) else extra_data
    except json.JSONDecodeError:
        extra = {}

    async with db_session() as db:
        # find channel connection
        conn = await db.get(ChannelConnection, channel_connection_id)
        if not conn:
            logger.warning("process_inbound: channel %s not found", channel_connection_id)
            return

        # find or create conversation
        conv = None
        if conversation_id:
            conv = await db.get(Conversation, conversation_id)
        if not conv:
            conv = (await db.execute(
                select(Conversation).where(
                    Conversation.channel == channel_type,
                    Conversation.channel_connection_id == channel_connection_id,
                ).order_by(Conversation.created_at.desc())
            )).scalars().first()

        if not conv:
            conv = Conversation(
                org_id=conn.org_id,
                channel=channel_type,
                channel_connection_id=channel_connection_id,
                agent_id=conn.agent_id,
                team_id=conn.team_id,
                extra_data=extra,
            )
            db.add(conv)
            await db.commit()
            await db.refresh(conv)

        # save inbound message
        msg = Message(
            conversation_id=conv.id,
            org_id=conn.org_id,
            role="user",
            content=text,
            extra_data=extra,
        )
        db.add(msg)
        await db.commit()

        # check org limits
        allowed, reason = await check_org_limits(conn.org_id, db)
        if not allowed:
            logger.warning("process_inbound: limit hit for org %s: %s", conn.org_id, reason)
            return

        # resolve agent or team
        agent_or_team = None
        if conn.agent_id:
            agent_or_team = await db.get(Agent, conn.agent_id)
        elif conn.team_id:
            agent_or_team = await db.get(
                Team, conn.team_id, options=[selectinload(Team.agents)]
            )

        if not agent_or_team:
            logger.warning("process_inbound: no agent/team for channel %s", channel_connection_id)
            return

        # run agent with retry + team failover
        reply_text = None
        try:
            if hasattr(agent_or_team, "agents"):  # Team
                from aios.core.orchestrator import TeamOrchestrator
                from aios.core.agent_health import health_tracker
                agents = list(agent_or_team.agents)
                # filter to available agents
                available = [a for a in agents if health_tracker.is_available(a.id)]
                if not available:
                    logger.warning("process_inbound: all agents in team %s are stopped", agent_or_team.id)
                    return
                orch = TeamOrchestrator(agent_or_team, available)
                reply_text = await orch.handle_message(conv.id, text)
                # if team failed, try each agent individually
                if not reply_text and len(available) > 1:
                    for agent in available:
                        try:
                            runtime = AgentRuntime(agent)
                            reply_text = await runtime.run(conv.id, text)
                            if reply_text:
                                break
                        except Exception:
                            logger.exception("Team failover: agent %s failed", agent.id)
            else:  # Agent
                from aios.core.agent import AgentRuntime
                runtime = AgentRuntime(agent_or_team)
                reply_text = await runtime.run(conv.id, text)

            if reply_text:
                # save reply
                db.add(Message(
                    conversation_id=conv.id,
                    org_id=conn.org_id,
                    role="assistant",
                    content=reply_text,
                    agent_id=getattr(agent_or_team, "id", None),
                ))
                await db.commit()
                await track_usage(conn.org_id, db, messages=1, tokens=len(reply_text))

                # deliver reply via channel (with retry + DLQ)
                await deliver_message(
                    ctx,
                    channel_connection_id,
                    conv.id,
                    reply_text,
                    json.dumps(extra),
                )
        except Exception as e:
            logger.exception("process_inbound: agent failed for conversation %s", conv.id)


# ARQ worker function registry
FUNCTIONS = [
    process_inbound,
    deliver_message,
]
