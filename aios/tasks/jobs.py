"""Async job definitions for ARQ worker.

Each top-level function is a job ARQ can execute.
Registered in FUNCTIONS list for the worker to discover.
"""

import json
import logging

from aios.core.delivery import deliver_message

logger = logging.getLogger(__name__)


_INBOUND_MAX_RETRIES = 3
_INBOUND_BASE_DELAY_S = 5.0


async def process_inbound(
    ctx,
    channel_type: str,
    channel_connection_id: str,
    conversation_id: str,
    text: str,
    user_id: str = "",
    extra_data: str = "{}",
    attempt: int = 1,
):
    """Process an inbound message from any channel, with retry + DLQ.

    Runs in ARQ worker: finds agent, runs it, sends reply via channel.
    Transient failures re-enqueue with backoff; after max attempts the
    message lands in the dead-letter queue.
    """
    try:
        await _process_inbound_once(
            ctx, channel_type, channel_connection_id, conversation_id, text, user_id, extra_data
        )
    except Exception as exc:
        logger.warning("process_inbound attempt %d/%d failed for %s/%s: %s",
                       attempt, _INBOUND_MAX_RETRIES, channel_type, conversation_id[:8], exc)
        if attempt < _INBOUND_MAX_RETRIES:
            from aios.tasks.queue import get_redis_pool
            pool = await get_redis_pool()
            await pool.enqueue_job(
                "aios.tasks.jobs.process_inbound",
                channel_type, channel_connection_id, conversation_id, text, user_id, extra_data,
                attempt + 1,
                _defer_seconds=_INBOUND_BASE_DELAY_S * (2 ** (attempt - 1)),
            )
        else:
            from aios.core.dead_letter import write_dlq
            await write_dlq(
                direction="inbound",
                channel_type=channel_type,
                job_name="aios.tasks.jobs.process_inbound",
                payload={
                    "args": [channel_type, channel_connection_id, conversation_id, text, user_id, extra_data],
                    "kwargs": {},
                },
                error=str(exc),
                channel_connection_id=channel_connection_id,
                conversation_id=conversation_id or None,
            )
            logger.error("DLQ: inbound %s/%s failed after %d attempts",
                         channel_type, conversation_id[:8], _INBOUND_MAX_RETRIES)


async def _process_inbound_once(
    ctx,
    channel_type: str,
    channel_connection_id: str,
    conversation_id: str,
    text: str,
    user_id: str = "",
    extra_data: str = "{}",
):
    """Single attempt at processing an inbound message."""
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
        # Exceptions propagate to process_inbound wrapper for retry/DLQ.
        reply_text = None
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


async def agent_run(ctx, payload: dict):
    """Distributed agent run via ARQ — dequeues scheduler, runs AgentRuntime with retry/DLQ."""
    agent_id = payload.get("agent_id")
    conv_id = payload.get("conv_id") or payload.get("conversation_id") or ""
    text = payload.get("text") or payload.get("message") or ""
    org_id = payload.get("org_id") or ""
    attempt = payload.get("attempt", 1)
    try:
        from aios.db.backend import db_session
        from aios.db.models import Agent as AgentModel
        from aios.core.agent import AgentRuntime
        from aios.db.engine import async_session as _sess
        async with _sess() as sess:
            agent = await sess.get(AgentModel, agent_id)
            if not agent:
                return {"error": "agent not found"}
            rt = AgentRuntime(agent)
            out = await rt.run(conv_id, text)
            return {"ok": True, "output": out[:2000]}
    except Exception as exc:
        if attempt < 3:
            from aios.tasks.queue import get_redis_pool
            try:
                pool = await get_redis_pool()
                await pool.enqueue_job("aios.tasks.jobs.agent_run", {**payload, "attempt": attempt + 1}, _defer_by=5 * (2 ** (attempt - 1)))
            except Exception:
                pass
        else:
            from aios.core.dead_letter import write_dlq
            await write_dlq(direction="outbound", channel_type="agent_run", job_name="aios.tasks.jobs.agent_run", payload=payload, error=str(exc), org_id=org_id or None, conversation_id=conv_id or None)
        raise


async def workflow_run_job(ctx, payload: dict):
    wf_id = payload.get("workflow_id")
    run_id = payload.get("run_id")
    try:
        from aios.db.backend import db_session
        from aios.db.models import Workflow, WorkflowRun
        from aios.core.workflow import WorkflowDef, WorkflowNode as WNode, WorkflowEngine
        from sqlalchemy.orm import selectinload
        from aios.db.engine import async_session as _sess
        async with _sess() as sess:
            wf = await sess.get(Workflow, wf_id, options=[selectinload(Workflow.nodes)])
            run = await sess.get(WorkflowRun, run_id)
            if not wf or not run:
                return
            wdef = WorkflowDef(id=wf.id, name=wf.name, timeout=wf.timeout_seconds, entry_node=wf.entry_node_id)
            for n in wf.nodes:
                wdef.nodes[n.id] = WNode(id=n.id, agent_id=n.agent_id, tool_name=n.tool_name, tool_args=n.tool_args or {}, depends_on=n.depends_on or [], condition=n.condition, output_key=n.output_key, timeout=n.timeout_seconds)
            eng = WorkflowEngine()
            res = await eng.run(wdef, run.conversation_id or run.id, (run.inputs or {}).get("input", ""))
            run.status = "done" if res.ok() else "failed"
            run.outputs = res.outputs
            run.node_status = res.node_status
            if res.errors:
                run.error = str(res.errors)
            await sess.commit()
    except Exception as exc:
        from aios.core.dead_letter import write_dlq
        await write_dlq(direction="outbound", channel_type="workflow", job_name="aios.tasks.jobs.workflow_run_job", payload=payload, error=str(exc))
        raise


# ARQ worker function registry
FUNCTIONS = [
    process_inbound,
    deliver_message,
    agent_run,
    workflow_run_job,
]
