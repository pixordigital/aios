"""Swarm coordinator — leader/worker, task distribution, consensus, shared memory.

Ruflo swarm pattern: agents self-organize, distribute tasks, vote, share memory.
Backed by team_swarm_configs + swarm_tasks + swarm_messages tables.
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, desc, func

from aios.db.backend import db_session
from aios.db.models import Agent, Conversation, SwarmMessage, SwarmTask, Team, TeamSwarmConfig, team_agents

logger = logging.getLogger(__name__)

_SWARM_MODES = {"supervisor", "consensus", "pipeline", "mesh"}


async def _team_belongs_to_org(db, team_id: str, org_id: str) -> bool:
    """Fail-closed team ownership check."""
    if not team_id or not org_id:
        return False
    return (
        await db.execute(select(Team.id).where(Team.id == team_id, Team.org_id == org_id))
    ).scalar_one_or_none() is not None


async def _agent_in_team(db, agent_id: str, team_id: str, org_id: str) -> bool:
    """Fail-closed agent membership check for team+org scope."""
    if not agent_id or not team_id or not org_id:
        return False
    return (
        await db.execute(
            select(team_agents.c.agent_id)
            .join(Agent, Agent.id == team_agents.c.agent_id)
            .where(
                team_agents.c.team_id == team_id,
                team_agents.c.agent_id == agent_id,
                Agent.org_id == org_id,
            )
        )
    ).scalar_one_or_none() is not None


async def _conversation_in_scope(
    db, conversation_id: str, *, team_id: str, org_id: str
) -> bool:
    """Fail-closed conversation ownership check."""
    if not conversation_id or not team_id or not org_id:
        return False
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.org_id != org_id:
        return False
    if conv.team_id and conv.team_id != team_id:
        return False
    return True


async def _depends_on_valid(db, depends_on: list[str], *, team_id: str, org_id: str) -> bool:
    """Fail-closed dependency ownership check. Empty deps are valid."""
    deps = [d for d in (depends_on or []) if d]
    if not deps:
        return True
    if not team_id or not org_id:
        return False
    rows = (
        await db.execute(
            select(SwarmTask.id, SwarmTask.task_id).where(
                SwarmTask.team_id == team_id,
                SwarmTask.org_id == org_id,
                (SwarmTask.id.in_(deps) | SwarmTask.task_id.in_(deps)),
            )
        )
    ).all()
    known: set[str] = set()
    for row_id, row_task_id in rows:
        known.add(row_id)
        if row_task_id:
            known.add(row_task_id)
    return all(d in known for d in deps)


async def _team_member_count(db, team_id: str, org_id: str) -> int:
    """Real team member count from team_agents; 0 if unknown/mismatch."""
    if not team_id or not org_id:
        return 0
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(team_agents)
                .join(Agent, Agent.id == team_agents.c.agent_id)
                .where(team_agents.c.team_id == team_id, Agent.org_id == org_id)
            )
        ).scalar()
        or 0
    )


class SwarmCoordinator:
    """Orchestrate distributed tasks across team members."""

    # ── Config ──

    async def ensure_config(self, team_id: str, org_id: str = "") -> TeamSwarmConfig | None:
        if not org_id:
            return None
        async with db_session() as db:
            team = (
                await db.execute(select(Team.id).where(Team.id == team_id, Team.org_id == org_id))
            ).scalar_one_or_none()
            if not team:
                return None
            cfg = (
                await db.execute(
                    select(TeamSwarmConfig).where(
                        TeamSwarmConfig.team_id == team_id, TeamSwarmConfig.org_id == org_id
                    )
                )
            ).scalar_one_or_none()
            if cfg:
                return cfg
            cfg = TeamSwarmConfig(team_id=team_id, org_id=org_id)
            db.add(cfg)
            await db.commit()
            await db.refresh(cfg)
            return cfg

    async def get_config(self, team_id: str, org_id: str = "") -> TeamSwarmConfig | None:
        if not org_id:
            return None
        async with db_session() as db:
            return (
                await db.execute(
                    select(TeamSwarmConfig).where(
                        TeamSwarmConfig.team_id == team_id, TeamSwarmConfig.org_id == org_id
                    )
                )
            ).scalar_one_or_none()

    async def update_config(self, team_id: str, *, org_id: str = "", **fields) -> TeamSwarmConfig | None:
        if not org_id:
            return None
        async with db_session() as db:
            cfg = (
                await db.execute(
                    select(TeamSwarmConfig).where(
                        TeamSwarmConfig.team_id == team_id, TeamSwarmConfig.org_id == org_id
                    )
                )
            ).scalar_one_or_none()
            if not cfg:
                return None
            for k, v in fields.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
            await db.commit()
            await db.refresh(cfg)
            return cfg

    # ── Task distribution ──

    async def dispatch(
        self, *, team_id: str, org_id: str, task_type: str = "agent_call",
        payload: dict | None = None, priority: int = 0,
        conversation_id: str | None = None, depends_on: list[str] | None = None,
        agent_id: str | None = None,
    ) -> SwarmTask | None:
        """Queue a task for swarm execution. Fail closed on org/team/membership/ownership mismatch."""
        async with db_session() as db:
            if not await _team_belongs_to_org(db, team_id, org_id):
                return None
            if agent_id and not await _agent_in_team(db, agent_id, team_id, org_id):
                return None
            if conversation_id and not await _conversation_in_scope(
                db, conversation_id, team_id=team_id, org_id=org_id
            ):
                return None
            deps = [d for d in (depends_on or []) if d]
            if not await _depends_on_valid(db, deps, team_id=team_id, org_id=org_id):
                return None
            task = SwarmTask(
                team_id=team_id, org_id=org_id, task_id=str(uuid.uuid4())[:16],
                task_type=task_type, payload=payload or {}, priority=priority,
                conversation_id=conversation_id, depends_on=deps,
                assigned_agent_id=agent_id, status="queued" if not agent_id else "assigned",
            )
            db.add(task)
            await db.commit()
            await db.refresh(task)
            return task

    async def claim(self, task_id: str, agent_id: str, org_id: str, team_id: str = "") -> SwarmTask | None:
        async with db_session() as db:
            task = await db.get(SwarmTask, task_id)
            if not task or task.org_id != org_id or task.status not in ("queued", "assigned"):
                # Fail closed: a task id from another tenant reads as missing.
                return None
            if team_id and task.team_id != team_id:
                return None
            if not await _agent_in_team(db, agent_id, task.team_id, org_id):
                return None
            task.assigned_agent_id = agent_id
            task.status = "running"
            task.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
            task.attempts += 1
            await db.commit()
            await db.refresh(task)
            return task

    async def complete(
        self, task_id: str, result: dict | None = None, error: str = "", org_id: str = "", team_id: str = "",
    ) -> SwarmTask | None:
        async with db_session() as db:
            task = await db.get(SwarmTask, task_id)
            if not task or (org_id and task.org_id != org_id):
                return None
            if team_id and task.team_id != team_id:
                return None
            task.result = result or {}
            task.error = error
            task.status = "failed" if error else "done"
            task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.commit()
            await db.refresh(task)
            return task

    async def list_tasks(
        self, *, team_id: str, status: str = "", limit: int = 20, org_id: str = "",
    ) -> list[SwarmTask]:
        async with db_session() as db:
            if not org_id or not await _team_belongs_to_org(db, team_id, org_id):
                # No org/team proof: refuse rather than dump another tenant's
                # task payloads. All API routes supply org_id.
                return []
            stmt = select(SwarmTask).where(SwarmTask.team_id == team_id, SwarmTask.org_id == org_id)
            if status:
                stmt = stmt.where(SwarmTask.status == status)
            stmt = stmt.order_by(desc(SwarmTask.priority), desc(SwarmTask.created_at)).limit(limit)
            result = await db.execute(stmt)
            return list(result.scalars().all())

    # ── Consensus ──

    async def vote(self, task_id: str, agent_id: str, vote: str, org_id: str = "", team_id: str = "") -> SwarmTask | None:
        """Record a consensus vote (approve|reject|abstain). Check threshold if reached."""
        async with db_session() as db:
            task = await db.get(SwarmTask, task_id)
            if not task or (org_id and task.org_id != org_id):
                return None
            if team_id and task.team_id != team_id:
                return None
            if not await _agent_in_team(db, agent_id, task.team_id, task.org_id):
                return None
            votes = dict(task.consensus_votes or {})
            votes[agent_id] = vote
            task.consensus_votes = votes
            # check threshold
            cfg = (await db.execute(select(TeamSwarmConfig).where(TeamSwarmConfig.team_id == task.team_id))).scalar_one_or_none()
            threshold = cfg.consensus_threshold if cfg else 0.6
            n_agents = await _team_member_count(db, task.team_id, task.org_id)
            if n_agents <= 0:
                task.status = "failed"
                task.error = "consensus denominator unavailable"
                await db.commit()
                await db.refresh(task)
                return task
            approves = sum(1 for v in votes.values() if v == "approve")
            if approves / n_agents >= threshold:
                task.status = "done"
                task.result = {"consensus": "approved", "votes": votes}
                task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            elif len(votes) >= n_agents:
                # all members voted but threshold not met → failed
                task.status = "failed"
                task.error = "consensus not reached"
                task.result = {"consensus": "rejected", "votes": votes}
            await db.commit()
            await db.refresh(task)
            return task

    # ── Shared memory ──

    async def put_shared(
        self, *, team_id: str, org_id: str, key: str, content: dict,
        sender_id: str | None = None, ttl_seconds: int = 3600,
        task_id: str | None = None,
    ) -> SwarmMessage | None:
        async with db_session() as db:
            if not await _team_belongs_to_org(db, team_id, org_id):
                return None
            if sender_id and not await _agent_in_team(db, sender_id, team_id, org_id):
                return None
            if task_id:
                task = await db.get(SwarmTask, task_id)
                if not task or task.org_id != org_id or task.team_id != team_id:
                    return None
            msg = SwarmMessage(
                team_id=team_id, org_id=org_id, swarm_task_id=task_id,
                sender_agent_id=sender_id, message_type="memory",
                content=content, memory_key=key, memory_ttl_seconds=ttl_seconds,
            )
            db.add(msg)
            await db.commit()
            await db.refresh(msg)
            return msg

    async def get_shared(
        self, *, team_id: str, key: str, org_id: str = "",
    ) -> SwarmMessage | None:
        async with db_session() as db:
            if not org_id or not await _team_belongs_to_org(db, team_id, org_id):
                return None
            stmt = select(SwarmMessage).where(
                SwarmMessage.team_id == team_id,
                SwarmMessage.org_id == org_id,
                SwarmMessage.memory_key == key,
            ).order_by(desc(SwarmMessage.created_at)).limit(1)
            result = await db.execute(stmt)
            msg = result.scalar_one_or_none()
            if not msg:
                return None
            # TTL check
            if msg.memory_ttl_seconds and msg.created_at:
                exp = msg.created_at + timedelta(seconds=msg.memory_ttl_seconds)
                if datetime.now(timezone.utc).replace(tzinfo=None) > exp:
                    return None
            return msg

    async def list_messages(
        self, *, team_id: str, limit: int = 20, org_id: str = "",
    ) -> list[SwarmMessage]:
        async with db_session() as db:
            if not org_id or not await _team_belongs_to_org(db, team_id, org_id):
                return []
            result = await db.execute(
                select(SwarmMessage).where(
                    SwarmMessage.team_id == team_id,
                    SwarmMessage.org_id == org_id,
                )
                .order_by(desc(SwarmMessage.created_at)).limit(limit)
            )
            return list(result.scalars().all())

    async def stats(self, team_id: str, org_id: str = "") -> dict:
        async with db_session() as db:
            if not org_id or not await _team_belongs_to_org(db, team_id, org_id):
                return {"total_tasks": 0, "queued": 0}
            base = [SwarmTask.team_id == team_id, SwarmTask.org_id == org_id]
            q = await db.execute(select(func.count(SwarmTask.id)).where(*base))
            total = q.scalar() or 0
            q2 = await db.execute(select(func.count(SwarmTask.id)).where(*base, SwarmTask.status == "queued"))
            queued = q2.scalar() or 0
            return {"total_tasks": total, "queued": queued}


swarm = SwarmCoordinator()
