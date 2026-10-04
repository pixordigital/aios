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
                _defer_by=_INBOUND_BASE_DELAY_S * (2 ** (attempt - 1)),
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


def _reply_meta(agent_or_team) -> dict:
    """Message insert fields for a reply.

    messages.agent_id is a FK to agents.id, so a Team must not be written there
    — that raised ForeignKeyViolationError on every team-bound channel. The team
    id goes in extra_data instead.
    """
    from aios.db.models import Team as _Team

    if isinstance(agent_or_team, _Team):
        return {"agent_id": None, "extra_data": {"team_id": agent_or_team.id}}
    return {"agent_id": agent_or_team.id, "extra_data": {}}


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
    from aios.core.agent import AgentRuntime
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

        # Find or create the conversation for THIS contact.
        #
        # The fallback used to be "latest conversation on this channel", which
        # put every customer of one Evolution number into a single thread: their
        # messages, the agent's replies, its memory and its RAG injections all
        # interleaved, and the inbox showed one row for the whole business.
        # A channel carries many contacts, so the thread is keyed by the
        # contact, not the channel.
        contact = extra.get("from_number") or user_id or ""
        conv = None
        if conversation_id:
            conv = await db.get(Conversation, conversation_id)
        if not conv and contact:
            conv = (await db.execute(
                select(Conversation).where(
                    Conversation.org_id == conn.org_id,
                    Conversation.channel == channel_type,
                    Conversation.channel_connection_id == channel_connection_id,
                    Conversation.external_id == contact,
                ).order_by(Conversation.created_at.desc())
            )).scalars().first()

        if not conv:
            conv = Conversation(
                org_id=conn.org_id,
                channel=channel_type,
                channel_connection_id=channel_connection_id,
                agent_id=conn.agent_id,
                team_id=conn.team_id,
                external_id=contact or None,
                extra_data=extra,
            )
            db.add(conv)
            try:
                await db.commit()
            except Exception:
                # Two workers handling the same contact's first message at once.
                # The unique index on (org, channel, connection, contact) is the
                # one that lost — take the winner's row instead of failing the
                # customer's message.
                await db.rollback()
                conv = (await db.execute(
                    select(Conversation).where(
                        Conversation.org_id == conn.org_id,
                        Conversation.channel == channel_type,
                        Conversation.channel_connection_id == channel_connection_id,
                        Conversation.external_id == contact,
                    ).order_by(Conversation.created_at.desc())
                )).scalars().first()
                if not conv:
                    raise
            await db.refresh(conv)

        # save inbound message
        # Provider message id -> idempotency key. Webhook retries (Slack sends
        # event retries, Evolution redelivers) used to insert a duplicate row
        # every time because channel_message_id was never populated.
        provider_msg_id = extra.get("msg_id") or extra.get("message_id") or None
        if not provider_msg_id and channel_type == "slack" and extra.get("ts"):
            provider_msg_id = f"slack:{extra.get('channel_id', '')}:{extra.get('ts')}"
        msg = None
        if provider_msg_id:
            dup = (await db.execute(
                select(Message).where(
                    Message.org_id == conn.org_id,
                    Message.channel_message_id == provider_msg_id,
                )
            )).scalars().first()
            # Only a *completed* attempt counts as a redelivery. The inbound row
            # is committed BEFORE the agent runs, so on any transient failure the
            # retry hit this same check, logged "duplicate ignored" and returned
            # success: the customer message was never answered, nothing landed in
            # the DLQ, and the ARQ job was recorded as fine. An incomplete row now
            # falls through and resumes instead of being discarded.
            if dup and (dup.extra_data or {}).get("inbound_completed"):
                logger.info("process_inbound: duplicate %s ignored (already handled)", provider_msg_id)
                return
            if dup:
                logger.info("process_inbound: resuming incomplete attempt for %s", provider_msg_id)
                msg = dup
        if msg is None:
            msg = Message(
                conversation_id=conv.id,
                org_id=conn.org_id,
                role="user",
                content=text,
                channel_message_id=provider_msg_id,
                extra_data=extra,
            )
            db.add(msg)
        try:
            await db.commit()
        except Exception as e:
            # Lost a race with another worker on the same redelivery. The
            # unique constraint on (org_id, channel_message_id) makes the
            # second insert fail; that IS the dedup working, not an error.
            # Anything else is real and must propagate.
            if "duplicate key" in str(e).lower() or "unique" in str(type(e).__name__).lower():
                logger.info("process_inbound: duplicate %s ignored (race)", provider_msg_id)
                return
            raise

        # check org limits
        allowed, reason = await check_org_limits(conn.org_id, db)
        if not allowed:
            # Deliberate refusal, not a crash: retrying cannot help. Record it
            # in the DLQ so the message is visible instead of silently dropped.
            logger.warning("process_inbound: limit hit for org %s: %s", conn.org_id, reason)
            from aios.core.dead_letter import write_dlq

            await write_dlq(
                direction="inbound",
                channel_type=channel_type,
                job_name="aios.tasks.jobs.process_inbound",
                payload={
                    "args": [channel_type, channel_connection_id, conv.id, text, user_id, extra_data],
                    "kwargs": {},
                },
                error=f"org limit: {reason}",
                org_id=conn.org_id,
                channel_connection_id=channel_connection_id,
                conversation_id=conv.id or None,
            )
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
                # Every agent is `stopped` in the health tracker. Nothing can
                # answer; record it rather than returning quietly.
                logger.warning("process_inbound: all agents in team %s are stopped", agent_or_team.id)
                from aios.core.dead_letter import write_dlq

                await write_dlq(
                    direction="inbound",
                    channel_type=channel_type,
                    job_name="aios.tasks.jobs.process_inbound",
                    payload={
                        "args": [channel_type, channel_connection_id, conv.id, text, user_id, extra_data],
                        "kwargs": {},
                    },
                    error="every agent in the team is stopped",
                    org_id=conn.org_id,
                    channel_connection_id=channel_connection_id,
                    conversation_id=conv.id or None,
                )
                return
            orch = TeamOrchestrator(agent_or_team, available)
            # db must be passed: without it AgentRuntime skips both the
            # check_org_limits gate and every Message write, so a team-bound
            # channel never recorded the agent's own replies — the next inbound
            # message reloaded history containing only the customer's turns and
            # the agent answered as if it had never spoken.
            reply_text = await orch.handle_message(conv.id, text, db)
            # if team failed, try each agent individually
            if not reply_text and len(available) > 1:
                for agent in available:
                    try:
                        runtime = AgentRuntime(agent)
                        reply_text = await runtime.run(conv.id, text, db)
                        if reply_text:
                            break
                    except Exception:
                        logger.exception("Team failover: agent %s failed", agent.id)
        else:  # Agent — 100% autônomo com HITL
            gov = (getattr(agent_or_team, "governance_config", None) or {})
            is_autonomous = gov.get("autonomous", True) or gov.get("autonomy") == "autonomous"
            if is_autonomous:
                from aios.core.autonomous_agent import AutonomousAgent
                auto = AutonomousAgent(agent_or_team)
                reply_text = await auto.run(conv.id, text, db)
                # Se HITL, reply_text já contém ⏸️ [HITL] — não tenta team failover
                if reply_text and "⏸️ [HITL]" in reply_text:
                    # Salva como pending e notifica canal mas não deliver como resposta normal
                    db.add(Message(
                        conversation_id=conv.id,
                        org_id=conn.org_id,
                        role="assistant",
                        content=reply_text,
                        **_reply_meta(agent_or_team),
                    ))
                    await db.commit()
                    # Ainda deliver para que humano veja no canal que precisa aprovar
                    await deliver_message(ctx, channel_connection_id, conv.id, reply_text, json.dumps(extra))
                    return
            else:
                from aios.core.agent import AgentRuntime
                runtime = AgentRuntime(agent_or_team)
                reply_text = await runtime.run(conv.id, text, db)

        if reply_text:
            # save reply
            db.add(Message(
                conversation_id=conv.id,
                org_id=conn.org_id,
                role="assistant",
                content=reply_text,
                **_reply_meta(agent_or_team),
            ))
            await db.commit()
            await track_usage(conn.org_id, db, messages=1, tokens=len(reply_text))

            # SDR -> CRM handoff. An answered conversation used to leave no
            # trace outside the agent's context window, so whoever picked the
            # lead up next inherited a name and a phone number and nothing
            # else. Runs after the reply is already committed and fails soft:
            # a customer must never lose their answer because the CRM write
            # failed. Matching is by phone, so a deal the agent created itself
            # during the run is the row that gets enriched, not duplicated.
            try:
                if getattr(agent_or_team, "agent_type", None) is not None:
                    from aios.core.crm_handoff import ensure_deal_for_contact, record_interaction

                    deal_id = await ensure_deal_for_contact(
                        db,
                        org_id=conn.org_id,
                        phone=contact or user_id,
                        name=(extra.get("from_name") or extra.get("pushName") or ""),
                        source=channel_type or "whatsapp",
                    )
                    if deal_id:
                        await record_interaction(
                            db,
                            deal_id,
                            conn.org_id,
                            agent_or_team.id,
                            inbound_text=text,
                            reply_text=reply_text,
                        )
                        await db.commit()
            except Exception as exc:
                logger.warning(
                    "crm handoff failed conv=%s: %s", getattr(conv, "id", "?"), exc
                )

            # Screen failures out before they reach the customer. A run that
            # failed does not raise — AgentRuntime returns a canned apology and
            # AutonomousAgent a reflection/HITL string — so without this the
            # "⏸️ [HITL]" control token and the internal reflection text were
            # delivered verbatim as if they were the answer.
            from aios.core.agent import is_failed_run

            if is_failed_run(reply_text):
                # Log it and let a human see it in the inbox. An escalation
                # channel (Slack/email) is the next step, not a guess here.
                logger.error(
                    "process_inbound: run failed for conv %s, not delivering: %s",
                    conv.id, reply_text[:200],
                )
                # Raise so the wrapper retries and, past the last attempt,
                # dead-letters the message. Returning quietly marked the ARQ job
                # green and set inbound_completed below, so a customer message
                # that produced no answer left no trace and nothing to retry.
                raise RuntimeError(
                    f"agent run produced no answer: {str(reply_text)[:200]}"
                )
            else:
                # deliver reply via channel (with retry + DLQ)
                await deliver_message(
                    ctx,
                    channel_connection_id,
                    conv.id,
                    reply_text,
                    json.dumps(extra),
                )

        # Event triggers. `fire_event_triggers` existed with zero callers, so
        # every "event" trigger the dashboard could create (documented event
        # type: message.received) was inert. Inbound is the event they describe.
        #
        # Published to the durable bus as well, not only to workflow triggers:
        # otherwise an agent subscribed to message.received (escalation,
        # sentiment watch, handoff) could never react, and "proactive agents"
        # would have nothing to observe on the highest-volume event.
        try:
            from aios.core.events import publish as publish_event

            await publish_event(
                "message.received",
                conn.org_id,
                {
                    "channel": channel_type,
                    "conversation_id": conv.id,
                    "channel_connection_id": channel_connection_id,
                    "text": text[:4000],
                    "user_id": user_id,
                    "answered": bool(reply_text),
                },
                # Conversation+message is the fact's identity, so an ARQ retry of
                # the same inbound does not re-trigger subscribers a second time.
                idempotency_key=f"msg:{channel_connection_id}:{getattr(msg, 'id', '') or conv.id}",
            )
        except Exception:
            logger.error("message.received publish failed conv=%s", getattr(conv, "id", "?"), exc_info=True)

        try:
            from aios.api.automations import fire_event_triggers

            await fire_event_triggers(
                "message.received",
                conn.org_id,
                {
                    "channel": channel_type,
                    "conversation_id": conv.id,
                    "channel_connection_id": channel_connection_id,
                    "text": text[:4000],
                    "user_id": user_id,
                    "answered": bool(reply_text),
                },
            )
        except Exception:
            logger.debug("event triggers failed for conv %s", getattr(conv, "id", "?"), exc_info=True)

        # Mark the inbound row handled. Until this flag is set a retry re-enters
        # and resumes the agent run; once set, a genuine provider redelivery is
        # skipped. Without it there was no way to tell those two cases apart.
        try:
            if msg is not None and msg.id:
                done = dict(msg.extra_data or {})
                done["inbound_completed"] = True
                msg.extra_data = done
                await db.commit()
        except Exception:
            logger.warning("process_inbound: could not mark %s completed", getattr(msg, "id", "?"))


async def agent_run(ctx, payload: dict):
    """Distributed agent run via ARQ — dequeues scheduler, runs AgentRuntime with retry/DLQ."""
    agent_id = payload.get("agent_id")
    conv_id = payload.get("conv_id") or payload.get("conversation_id") or ""
    text = payload.get("text") or payload.get("message") or ""
    org_id = payload.get("org_id") or ""
    attempt = payload.get("attempt", 1)
    try:
        from aios.db.models import Agent as AgentModel

        from aios.db.engine import async_session as _sess
        async with _sess() as sess:
            agent = await sess.get(AgentModel, agent_id)
            if not agent:
                return {"error": "agent not found"}
            gov = (agent.governance_config or {})
            is_autonomous = gov.get("autonomous", True) or gov.get("autonomy") == "autonomous"
            if is_autonomous:
                from aios.core.autonomous_agent import AutonomousAgent
                auto = AutonomousAgent(agent)
                out = await auto.run(conv_id, text, sess)
            else:
                from aios.core.agent import AgentRuntime
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


async def quota_alert_job(ctx, payload: dict):
    from aios.core.limits import _send_quota_alert

    await _send_quota_alert(payload.get("org_id"), payload.get("pct", 0), payload.get("plan", ""))


def render_event_instruction(ev) -> str:
    """Turn an event into the instruction an autonomous agent receives.

    A named function so the wording is testable and stable — subscribed agents
    start depending on this text, and a silent rewording would change the
    behaviour of every one of them.
    """
    payload = json.dumps(ev.payload, ensure_ascii=False, default=str)[:4000]
    return (
        f"[event] {ev.event_type}\n"
        f"occurred_at: {ev.ts}\n"
        f"event_id: {ev.event_id}\n"
        f"data: {payload}\n\n"
        "You are subscribed to this event type. Decide and act autonomously: "
        "if it needs action, use your tools and do it now; if it needs no "
        "action, do nothing. Do not ask for confirmation unless a tool "
        "requires approval."
    )


async def event_consume_job(ctx, payload: dict | None = None):
    """Drain the durable event stream and dispatch to subscribed agents.

    Registered as an ARQ cron job: the timer is only a wake-up nudge, the work
    is still event-driven — no event, no agent activity. A job rather than a
    long-lived loop so a crash is a retry instead of a dead consumer, and so a
    second web replica cannot spawn a competing reader.
    """
    from aios.core.events import consume_once

    return {"handled": await consume_once(block_ms=1000, count=20)}


async def proactive_event_job(ctx, payload: dict):
    """Run one agent because it subscribed to the dispatched event.

    Unlike ``agent_run`` there is no inbound message to answer, so the event
    becomes an instruction and the agent chooses what to do with it.
    """
    from aios.core.events import EventEnvelope, ev_type_matches, publish, subscriptions_for
    from aios.db.engine import async_session as _sess
    from aios.db.models import Agent as AgentModel

    event = payload.get("event") or {}
    agent_id = payload.get("agent_id", "")
    org_id = payload.get("org_id", "")
    ev = EventEnvelope.from_dict(event)

    try:
        async with _sess() as sess:
            agent = await sess.get(AgentModel, agent_id)
            # org check is the tenant boundary: a dispatched agent that is not
            # in the event's org is a routing bug, not a transient failure.
            if not agent or agent.org_id != org_id:
                logger.error("proactive_event_job: agent %s not in org %s", agent_id, org_id)
                return {"error": "agent not found in org"}

            # Re-check the subscription: it may have been removed between
            # publish and dispatch, and a stale run must not execute.
            if not any(ev_type_matches(ev.event_type, s) for s in subscriptions_for(agent)):
                logger.info(
                    "proactive_event_job: %s no longer subscribes to %s", agent_id, ev.event_type
                )
                return {"skipped": "unsubscribed"}

            instruction = render_event_instruction(ev)
            gov = agent.governance_config or {}
            is_autonomous = gov.get("autonomous", True) or gov.get("autonomy") == "autonomous"

            # Same execution path as inbound runs, so governance, model routing,
            # memory and tool guards behave identically for proactive work.
            if is_autonomous:
                from aios.core.autonomous_agent import AutonomousAgent

                out = await AutonomousAgent(agent).run("", instruction, sess)
            else:
                from aios.core.agent import AgentRuntime

                # No db arg: AgentRuntime takes a DatabaseBackend, not the
                # AsyncSession this job holds. Same call shape as agent_run.
                out = await AgentRuntime(agent).run("", instruction)

            # Emit what the agent did so downstream automations can react too.
            await publish(
                "agent.proactive_completed",
                org_id,
                {
                    "agent_id": agent_id,
                    "agent_name": agent.name,
                    "source_event": ev.event_type,
                    "source_event_id": ev.event_id,
                    "output": str(out)[:4000],
                },
                actor_id=agent_id,
                idempotency_key=f"{ev.idempotency_key}:{agent_id}:done",
            )
            return {"ok": True, "agent_id": agent_id, "output": str(out)[:2000]}
    except Exception as exc:
        logger.exception("proactive_event_job failed agent=%s event=%s", agent_id, ev.event_type)
        from aios.core.dead_letter import write_dlq

        await write_dlq(
            direction="outbound",
            channel_type="proactive_event",
            job_name="aios.tasks.jobs.proactive_event_job",
            payload=payload,
            error=str(exc),
            org_id=org_id or None,
        )
        raise


async def workday_job(ctx):
    """Clock every proactive agent in and hand it its board for the day.

    This is the piece that makes an agent behave like an employee rather than a
    reaction function. `proactive_event_job` only ever ran an agent when
    something had been published, so an agent with no subscriptions to anything
    did nothing, ever. A Closer with fifty open deals had no way to learn that.

    It runs from the work the agent already owns rather than from a new table:
    its open deals, ranked by the timing score, with due follow-ups first. So
    the board reflects yesterday simply because yesterday was recorded.

    One agent failing must not cost the others their morning, so each run is
    isolated. Failures are logged and dead-lettered rather than raised: a raise
    here would abandon every agent after the first.
    """
    from sqlalchemy import select

    from aios.core.workday import (
        board_for_agent,
        org_workday_enabled,
        render_board,
        should_work_day,
    )
    from aios.db.backend import db_session
    from aios.db.models import Agent, Organization

    worked, empty, failed, paused = 0, 0, 0, 0
    # Per-org, because each org has its own owner to tell. A single global
    # digest would report another tenant's numbers to whoever reads it.
    by_org: dict[str, dict] = {}

    async with db_session() as db:
        orgs = (
            await db.execute(
                select(Organization).where(Organization.is_active == True)  # noqa: E712
            )
        ).scalars().all()
        # The org switch is checked here and nowhere subtler, so "off" is
        # unambiguous: no org means no run, and the per-agent flag cannot
        # re-enable a paused org on its own.
        live = [o for o in orgs if org_workday_enabled(o)]
        paused = len(orgs) - len(live)
        agents = (
            await db.execute(
                select(Agent).where(
                    Agent.org_id.in_([o.id for o in live]), Agent.status == "active"
                )
            )
        ).scalars().all()

    for agent in agents:
        if not should_work_day(agent):
            continue
        try:
            async with db_session() as db:
                fresh = await db.get(Agent, agent.id)
                if not fresh or not should_work_day(fresh):
                    continue
                board = await board_for_agent(fresh, db)
                instruction = render_board(board)
                if not instruction:
                    empty += 1
                    continue

                gov = fresh.governance_config or {}
                is_autonomous = gov.get("autonomous", True) or gov.get("autonomy") == "autonomous"
                if is_autonomous:
                    from aios.core.autonomous_agent import AutonomousAgent

                    out = await AutonomousAgent(fresh).run("", instruction, db)
                else:
                    from aios.core.agent import AgentRuntime

                    out = await AgentRuntime(fresh).run("", instruction)
                worked += 1
                _stats = by_org.setdefault(fresh.org_id, {"worked": 0, "failed": 0, "failures": []})
                _stats["worked"] += 1

                from aios.core.events import publish as publish_event

                await publish_event(
                    "agent.workday_completed",
                    fresh.org_id,
                    {
                        "agent_id": fresh.id,
                        "agent_name": fresh.name,
                        "items": board["count"],
                        "overdue": board["overdue"],
                        "output": str(out)[:4000],
                    },
                    actor_id=fresh.id,
                    # One board per agent per day. Without this a retried or
                    # duplicated run would have the agent work the same deals
                    # twice, which is worse than not working them.
                    idempotency_key=f"workday:{fresh.id}:{board['date']}",
                )
        except Exception as exc:
            failed += 1
            _stats = by_org.setdefault(agent.org_id, {"worked": 0, "failed": 0, "failures": []})
            _stats["failed"] += 1
            _stats["failures"].append((agent.name or agent.id, str(exc)))
            logger.exception("workday failed for agent %s: %s", agent.id, exc)

    # The owner asked to be kept aware, and a workday that runs silently is the
    # one thing worse than no workday: agents act and nobody hears about it.
    # Failures lead the message, because "3 agents failed" buried under deal
    # counts is the part that actually matters.
    try:
        await _notify_owner_digest(by_org)
    except Exception:
        logger.exception("workday digest failed")

    logger.info(
        "workday: %d worked, %d empty board, %d failed, %d org(s) opted out",
        worked, empty, failed, paused,
    )
    return {"worked": worked, "empty": empty, "failed": failed, "orgs_paused": paused}


async def _notify_owner_digest(by_org: dict):
    """One Slack message per org: who worked their board, and what broke.

    Failures lead the message. "3 agents failed" buried under deal counts is the
    part that actually matters, and a digest that only reports the good news is
    how a channel stops being read.
    """
    from aios.core.meetings import human_slack_targets, post_to_slack

    for org_id, stats in (by_org or {}).items():
        worked = stats.get("worked", 0)
        failed = stats.get("failed", 0)
        failures = stats.get("failures", [])
        if worked == 0 and failed == 0:
            # Nothing happened. A daily "nothing happened" is how people learn
            # to ignore the channel.
            continue

        targets = await human_slack_targets(org_id, team_id="")
        if not targets:
            logger.info("workday digest skipped for org %s: no owner Slack DM", org_id)
            continue

        plural = "s" if worked != 1 else ""
        body = f"*Jornada diária* — {worked} agente{plural} trabalharam a fila"
        if failed:
            body += f"\n:rotating_light: *{failed} falharam* e precisam de olhada"
        if failures:
            rows = "\n".join(f"• `{name}`: {err[:140]}" for name, err in failures[:10])
            body += f"\n\n*Falhas:*\n{rows}"
        if stats.get("paused"):
            body += "\n\n_Organizações com a jornada pausada: este turno foi menor._"

        try:
            await post_to_slack(body, targets)
        except Exception:
            logger.warning("workday digest post failed org=%s", org_id, exc_info=True)


async def budget_alert_job(ctx, payload: dict):
    """Delivered by limits.py when a budget crosses 80/90/100%.

    This job did not exist: enqueue_job to a missing ARQ function fails at
    runtime, so no budget alert ever fired. Registered in FUNCTIONS below.
    """
    from aios.core.limits import _send_budget_alert

    await _send_budget_alert(
        payload.get("org_id"),
        payload.get("budget_id", ""),
        payload.get("pct", 0),
        payload.get("spent_brl", 0.0),
    )


async def transcribe_voice_recording(ctx, recording_id: str, language: str = "pt"):
    """Transcribe a voice recording using Whisper."""
    from aios.db.backend import db_session
    from aios.db.models import VoiceRecording
    from aios.core.storage import backend

    logger.info("Starting transcription for recording %s", recording_id)

    
    try:
        async with db_session() as db:
            recording = await db.get(VoiceRecording, recording_id)
            if not recording:
                logger.error("Recording %s not found", recording_id)
                return {"error": "Recording not found"}
            
            if not recording.recording_storage_path:
                recording.transcript_status = "failed"
                await db.commit()
                return {"error": "No audio file"}
            
            # Read audio file
            audio_content = await backend().read(recording.recording_storage_path)
            if not audio_content:
                recording.transcript_status = "failed"
                await db.commit()
                return {"error": "Audio file not found in storage"}
            
            # Call Whisper API
            import httpx
            # ctx["settings"] is a plain dict, so getattr() always returned the
            # default and any configured voice_stt_url was silently ignored --
            # transcription always went to http://voice-stt:9000 even when the
            # operator pointed it somewhere else.
            from aios.config import settings as _cfg
            _s = ctx.get("settings") or {}
            _stt = _s.get("voice_stt_url") if isinstance(_s, dict) else getattr(_s, "voice_stt_url", None)
            whisper_url = _stt or _cfg.voice_stt_url or ""
            if not whisper_url:
                # No STT configured. Defaulting to a host that only exists under
                # an opt-in compose profile turned every transcription into a DNS
                # failure; say so plainly instead.
                recording.transcript_status = "failed"
                await db.commit()
                return {"error": "no STT configured (AIOS_VOICE_STT_URL)"}

            async with httpx.AsyncClient(timeout=300) as client:
                files = {"file": (f"recording-{recording.call_sid}.mp3", audio_content, "audio/mpeg")}
                data = {"language": language, "response_format": "text"}
                resp = await client.post(f"{whisper_url.rstrip('/')}/asr", files=files, data=data)

                if resp.status_code == 200:
                    # whisper-asr-webservice answers {"text": ...} as JSON even
                    # when response_format=text, so storing resp.text verbatim
                    # put a JSON blob in the transcript field.
                    raw = resp.text.strip()
                    transcript = raw
                    if raw.startswith("{"):
                        try:
                            transcript = json.loads(raw).get("text", raw)
                        except json.JSONDecodeError:
                            transcript = raw
                    recording.transcript = transcript
                    recording.transcript_status = "completed"
                    recording.transcript_language = language
                    await db.commit()
                    logger.info("Transcription completed for recording %s", recording_id)
                    return {"ok": True, "transcript": transcript}
                else:
                    recording.transcript_status = "failed"
                    await db.commit()
                    logger.error("Whisper transcription failed: %s", resp.text)
                    return {"error": f"Whisper error: {resp.text}"}
                    
    except Exception as e:
        logger.exception("Transcription failed for recording %s", recording_id)
        try:
            async with db_session() as db:
                recording = await db.get(VoiceRecording, recording_id)
                if recording:
                    recording.transcript_status = "failed"
                    await db.commit()
        except Exception:
            pass
        return {"error": str(e)}


async def download_voice_recording(ctx, recording_id: str, recording_url: str):
    """Download a voice recording from URL and store in S3/local storage."""
    from aios.db.backend import db_session
    from aios.db.models import VoiceRecording
    from aios.core.storage import save_artifact
    import httpx
    
    # Log the host only: provider recording URLs carry auth query params.
    from urllib.parse import urlparse as _urlparse

    try:
        _host = _urlparse(recording_url or "").hostname or "?"
    except Exception:
        _host = "?"
    logger.info("Downloading voice recording %s from %s", recording_id, _host)

    # recording_url arrives in the voice webhook body. The webhook is secret-
    # gated, but the URL itself is caller-controlled — fetch it through the
    # same SSRF guard as every other agent-fetched URL.
    from aios.tools.ssrf import check_url

    blocked = check_url(recording_url or "")
    if blocked:
        logger.warning("Recording download blocked (SSRF): %s", blocked)
        return {"error": f"URL bloqueada: {blocked}"}

    try:
        async with db_session() as db:
            recording = await db.get(VoiceRecording, recording_id)
            if not recording:
                logger.error("Recording %s not found", recording_id)
                return {"error": "Recording not found"}
            
            # Download audio file
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(recording_url)
                if resp.status_code != 200:
                    logger.error("Failed to download recording: %s", resp.status_code)
                    return {"error": f"Download failed: {resp.status_code}"}
                
                audio_content = resp.content
            
            # Save to storage
            filename = f"recording-{recording.call_sid}.mp3"
            result = await save_artifact(
                db=db,
                org_id=recording.org_id,
                filename=filename,
                content=audio_content,
                content_type="audio/mpeg",
                conversation_id=recording.conversation_id,
                description=f"Voice recording for call {recording.call_sid}",
            )
            
            recording.recording_storage_path = result["id"]
            recording.duration_seconds = len(audio_content) // 32000  # rough estimate for mp3
            await db.commit()
            
            logger.info("Downloaded and saved recording %s", recording_id)
            
            # Queue transcription
            from aios.tasks.queue import enqueue_job
            await enqueue_job("transcribe_voice_recording", recording_id=recording_id, language="pt")
            
            return {"ok": True, "storage_path": result["id"]}
            
    except Exception as e:
        logger.exception("Download failed for recording %s", recording_id)
        return {"error": str(e)}


async def process_commitment_at_risk(ctx, payload: dict, business_trace_id: str | None = None):
    """Run agent for commitment.at_risk and publish agent.action.completed via outbox."""
    from aios.config import settings

    if not settings.arvo_integration_enabled or not settings.arvo_base_url:
        return {"skipped": True, "reason": "integration disabled"}

    import uuid

    from aios.db.engine import async_session
    from aios.db.models import Agent
    from sqlalchemy import select

    org_id = payload.get("org_id") or payload.get("orgId") or ""
    finding_id = payload.get("finding_id") or payload.get("opportunity_id") or payload.get("id") or "unknown"
    business_trace_id = business_trace_id or payload.get("business_trace_id") or str(finding_id)

    agent = None
    if org_id:
        try:
            async with async_session() as s:
                q = await s.execute(select(Agent).where(Agent.org_id == org_id, Agent.status == "active").limit(1))
                agent = q.scalars().first()
        except Exception:
            logger.exception("commitment.at_risk agent lookup failed")

    if not agent:
        logger.error(
            "commitment.at_risk skipped: no active agent for organization %s",
            org_id,
        )
        return {"skipped": True, "reason": "no active agent"}

    try:
        gov = agent.governance_config or {}
        is_auto = gov.get("autonomous") is True or gov.get("autonomy") == "autonomous"
        conv_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"commitment:{finding_id}:{business_trace_id}"))
        msg = f"Commitment at risk: {finding_id}. Details: {payload}. Trace {business_trace_id}. Provide action plan concise."
        if is_auto:
            from aios.core.autonomous_agent import AutonomousAgent
            auto = AutonomousAgent(agent)
            result_text = await auto.run(conv_id, msg)
        else:
            from aios.core.agent import AgentRuntime
            rt = AgentRuntime(agent)
            result_text = await rt.run(conv_id, msg)
    except Exception:
        logger.exception("commitment.at_risk agent execution failed")
        raise

    try:
        from aios.integrations.arvo.publisher import enqueue_outbox
        await enqueue_outbox(
            "agent.action.completed",
            {"finding_id": str(finding_id), "org_id": org_id, "output": result_text[:2000], "agent_id": getattr(agent, "id", None) if agent else None},
            business_trace_id=str(business_trace_id),
            idempotency_key=f"agent.action.completed:{business_trace_id}"[:128],
        )
    except Exception:
        logger.exception("publish agent.action.completed failed")
        raise

    return {"finding_id": str(finding_id), "business_trace_id": str(business_trace_id), "output": result_text[:500]}


async def weekly_standup_job(ctx):
    """Monday 9h (cron daily, self-skips): post team progress to Slack team channels."""
    from datetime import date

    from sqlalchemy import select

    if date.today().weekday() != 0:
        return {"skipped": True, "reason": "not-monday"}
    from aios.core.meetings import post_to_slack, standup_text, team_week_stats
    from aios.core.sales_goals import month_progress
    from aios.db.backend import db_session
    from aios.db.models import Agent, ChannelConnection, Organization, Team

    posted, failed = 0, 0
    async with db_session() as db:
        import asyncio as _aio

        orgs = (await db.execute(select(Organization).where(Organization.is_active == True))).scalars().all()  # noqa: E712
        for org in orgs:
            conns = (await db.execute(select(ChannelConnection).where(
                ChannelConnection.org_id == org.id,
                ChannelConnection.channel_type == "slack",
                ChannelConnection.is_active == True,  # noqa: E712
                ChannelConnection.team_id != None,  # noqa: E711
            ))).scalars().all()
            # Batch the per-connection lookups: one query for teams, one for
            # managers, instead of 2N round-trips inside the loop.
            wanted = [c for c in conns
                      if isinstance(c.config or {}, dict) and not (c.config or {}).get("slack_1on1")]
            team_ids = {c.team_id for c in wanted if c.team_id}
            teams = {}
            if team_ids:
                teams = {t.id: t for t in (await db.execute(
                    select(Team).where(Team.id.in_(team_ids)))).scalars().all()}
            mgr_ids = {t.manager_agent_id for t in teams.values() if t.manager_agent_id}
            managers = {}
            if mgr_ids:
                managers = {a.id: a for a in (await db.execute(
                    select(Agent).where(Agent.id.in_(mgr_ids)))).scalars().all()}
            for conn in wanted:
                cfg = conn.config or {}
                channel = cfg.get("slack_channel_id", "")
                token = cfg.get("bot_token", "")
                team = teams.get(conn.team_id)
                if not team or not channel or not token:
                    continue
                manager = managers.get(team.manager_agent_id) if team.manager_agent_id else None
                stats = await team_week_stats(db, org.id, team.id)
                try:
                    goal = await month_progress(db, org.id, team_id=team.id)
                except Exception:
                    goal = None
                text = standup_text(team.name, manager.name if manager else "-", stats, goal)
                # post_to_slack is sync urllib: keep it off the event loop.
                if await _aio.to_thread(post_to_slack, token, channel, text):
                    posted += 1
                else:
                    failed += 1
    return {"posted": posted, "failed": failed}


async def _post_team_reports(kind: str, year_month: str | None = None,
                             since=None, until=None) -> dict:
    """Build + post one report per team to the owner's Slack DM.

    Shared by weekly_report_job and monthly_report_job. Walks orgs → active
    slack connections → teams, and resolves managers in two batched queries
    rather than 2N round-trips inside the loop.
    """
    from aios.core.meetings import (
        manager_narrative,
        post_to_slack,
        report_targets,
        report_text,
        team_stats,
    )
    from aios.core.sales_goals import month_progress
    from aios.db.backend import db_session
    from aios.db.models import Agent, ChannelConnection, Organization, Team
    from sqlalchemy import select

    posted, failed, no_manager, silent = 0, 0, 0, 0
    async with db_session() as db:
        import asyncio as _aio

        orgs = (await db.execute(
            select(Organization).where(Organization.is_active == True)  # noqa: E712
        )).scalars().all()
        for org in orgs:
            conns = (await db.execute(select(ChannelConnection).where(
                ChannelConnection.org_id == org.id,
                ChannelConnection.channel_type == "slack",
                ChannelConnection.is_active == True,  # noqa: E712
                ChannelConnection.team_id != None,  # noqa: E711
            ))).scalars().all()
            if not conns:
                continue
            team_ids = {c.team_id for c in conns if c.team_id}
            teams = {}
            if team_ids:
                teams = {t.id: t for t in (await db.execute(
                    select(Team).where(Team.id.in_(team_ids)))).scalars().all()}
            mgr_ids = {t.manager_agent_id for t in teams.values() if t.manager_agent_id}
            managers = {}
            if mgr_ids:
                managers = {a.id: a for a in (await db.execute(
                    select(Agent).where(Agent.id.in_(mgr_ids)))).scalars().all()}

            for team in teams.values():
                manager = managers.get(team.manager_agent_id) if team.manager_agent_id else None
                if manager is None:
                    # No manager means no owner for the team and nobody to carry
                    # the remediation plan. Counted, not guessed around.
                    no_manager += 1
                    continue
                targets = report_targets(conns, team.id)
                if not targets:
                    continue

                stats = await team_stats(db, org.id, team.id, days=7, since=since, until=until)
                try:
                    goal = await month_progress(db, org.id, year_month, team_id=team.id)
                except Exception:
                    logger.exception("report: goal progress failed for team %s", team.id)
                    goal = None
                # The manager narrates its own numbers. This is a full agent
                # run, so it costs an LLM call per team per week — that is the
                # point of the report, not a template.
                narrative = await manager_narrative(manager, team, stats, goal, kind)
                if not narrative:
                    silent += 1
                text = report_text(
                    kind, team.name, manager.name, stats, goal, narrative
                )
                for t in targets:
                    # post_to_slack is sync urllib: keep it off the event loop.
                    if await _aio.to_thread(post_to_slack, t["token"], t["channel"], text):
                        posted += 1
                    else:
                        failed += 1
    return {
        "kind": kind,
        "posted": posted,
        "failed": failed,
        "teams_without_manager": no_manager,
        "teams_manager_silent": silent,
    }


async def weekly_report_job(ctx):
    """Monday 9h15 (cron daily, self-skips): weekly report + 1:1 agenda to the owner."""
    from datetime import date

    if date.today().weekday() != 0:
        return {"skipped": True, "reason": "not-monday"}
    return await _post_team_reports("weekly")


async def monthly_report_job(ctx):
    """1st of month 9h30 (cron daily, self-skips): last month's report to the owner."""
    from datetime import date, timedelta

    if date.today().day != 1:
        return {"skipped": True, "reason": "not-first-of-month"}

    from aios.core.sales_goals import _month_bounds

    prev_month = (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    start, end = _month_bounds(prev_month)
    return await _post_team_reports(
        "monthly", year_month=prev_month, since=start, until=end
    )


# ARQ worker function registry
FUNCTIONS = [
    process_inbound,
    deliver_message,
    agent_run,
    workflow_run_job,
    quota_alert_job,
    budget_alert_job,
    transcribe_voice_recording,
    download_voice_recording,
    process_commitment_at_risk,
    weekly_standup_job,
    weekly_report_job,
    monthly_report_job,
    event_consume_job,
    proactive_event_job,
    workday_job,
]


async def template_status_reconcile_job(ctx, payload: dict | None = None):
    """Re-pull template status from Meta for anything stuck in review.

    Meta's review takes up to 24h and webhooks are dropped silently, so a
    webhook-only design leaves templates stuck in PENDING forever. Re-query any
    template that has been PENDING for a while, one connection at a time so a
    rate-limited WABA does not block the others.
    """
    from sqlalchemy import select
    from aios.db.backend import db_session
    from aios.core.meta_api import MetaAPIError
    from aios.db.models import WhatsappConnection, WhatsappTemplate
    from datetime import datetime, timedelta, timezone

    stale_before = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    async with db_session() as db:
        conns = (await db.execute(
            select(WhatsappConnection).where(WhatsappConnection.status == "verified")
        )).scalars().all()
    if not conns:
        return {"checked": 0}

    from aios.dashboard.app import _wa_meta_client, _wa_apply_meta_state

    checked = updated = 0
    for conn in conns:
        try:
            async with db_session() as db:
                pending = (await db.execute(
                    select(WhatsappTemplate).where(
                        WhatsappTemplate.org_id == conn.org_id,
                        WhatsappTemplate.status == "PENDING",
                        WhatsappTemplate.meta_template_id.is_not(None),
                        WhatsappTemplate.submitted_at.is_not(None),
                        WhatsappTemplate.submitted_at < stale_before,
                    )
                )).scalars().all()
                if not pending:
                    continue
                client = _wa_meta_client(conn)
                for tpl in pending:
                    checked += 1
                    try:
                        info = await client.get_template(tpl.meta_template_id)
                    except MetaAPIError:
                        # 80008 means we are being rate limited; stop this WABA and
                        # leave the rows PENDING for the next tick.
                        logger.warning("template reconcile rate-limited org=%s", conn.org_id)
                        break
                    _wa_apply_meta_state(tpl, info)
                    tpl.last_synced_at = now
                    updated += 1
                await db.commit()
        except Exception:
            logger.exception("template reconcile failed org=%s", conn.org_id)
            continue
    logger.info("template reconcile: checked=%d updated=%d", checked, updated)
    return {"checked": checked, "updated": updated}
