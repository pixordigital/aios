"""Swarm coordinator — leader/worker, task distribution, consensus, shared memory.

Ruflo swarm pattern: agents self-organize, distribute tasks, vote, share memory.
Backed by team_swarm_configs + swarm_tasks + swarm_messages tables.
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, desc, func, update

from aios.db.backend import db_session
from aios.db.models import TeamSwarmConfig, SwarmTask, SwarmMessage, Team

logger = logging.getLogger(__name__)

_SWARM_MODES = {"supervisor", "consensus", "pipeline", "mesh"}


class SwarmCoordinator:
    """Orchestrate distributed tasks across team members."""

    # ── Config ──

    async def ensure_config(self, team_id: str, org_id: str) -> TeamSwarmConfig:
        async with db_session() as db:
            cfg = (await db.execute(select(TeamSwarmConfig).where(TeamSwarmConfig.team_id == team_id))).scalar_one_or_none()
            if cfg:
                return cfg
            cfg = TeamSwarmConfig(team_id=team_id, org_id=org_id)
            db.add(cfg)
            await db.commit()
            await db.refresh(cfg)
            return cfg

    async def get_config(self, team_id: str) -> TeamSwarmConfig | None:
        async with db_session() as db:
            return (await db.execute(select(TeamSwarmConfig).where(TeamSwarmConfig.team_id == team_id))).scalar_one_or_none()

    async def update_config(self, team_id: str, **fields) -> TeamSwarmConfig | None:
        async with db_session() as db:
            cfg = (await db.execute(select(TeamSwarmConfig).where(TeamSwarmConfig.team_id == team_id))).scalar_one_or_none()
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
    ) -> SwarmTask:
        """Queue a task for swarm execution."""
        async with db_session() as db:
            task = SwarmTask(
                team_id=team_id, org_id=org_id, task_id=str(uuid.uuid4())[:16],
                task_type=task_type, payload=payload or {}, priority=priority,
                conversation_id=conversation_id, depends_on=depends_on or [],
                assigned_agent_id=agent_id, status="queued" if not agent_id else "assigned",
            )
            db.add(task)
            await db.commit()
            await db.refresh(task)
            return task

    async def claim(self, task_id: str, agent_id: str) -> SwarmTask | None:
        async with db_session() as db:
            task = await db.get(SwarmTask, task_id)
            if not task or task.status not in ("queued", "assigned"):
                return None
            task.assigned_agent_id = agent_id
            task.status = "running"
            task.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
            task.attempts += 1
            await db.commit()
            await db.refresh(task)
            return task

    async def complete(self, task_id: str, result: dict | None = None, error: str = "") -> SwarmTask | None:
        async with db_session() as db:
            task = await db.get(SwarmTask, task_id)
            if not task:
                return None
            task.result = result or {}
            task.error = error
            task.status = "failed" if error else "done"
            task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.commit()
            await db.refresh(task)
            return task

    async def list_tasks(
        self, *, team_id: str, status: str = "", limit: int = 20,
    ) -> list[SwarmTask]:
        async with db_session() as db:
            stmt = select(SwarmTask).where(SwarmTask.team_id == team_id)
            if status:
                stmt = stmt.where(SwarmTask.status == status)
            stmt = stmt.order_by(desc(SwarmTask.priority), desc(SwarmTask.created_at)).limit(limit)
            result = await db.execute(stmt)
            return list(result.scalars().all())

    # ── Consensus ──

    async def vote(self, task_id: str, agent_id: str, vote: str) -> SwarmTask | None:
        """Record a consensus vote (approve|reject|abstain). Check threshold if reached."""
        async with db_session() as db:
            task = await db.get(SwarmTask, task_id)
            if not task:
                return None
            votes = dict(task.consensus_votes or {})
            votes[agent_id] = vote
            task.consensus_votes = votes
            # check threshold
            cfg = (await db.execute(select(TeamSwarmConfig).where(TeamSwarmConfig.team_id == task.team_id))).scalar_one_or_none()
            threshold = cfg.consensus_threshold if cfg else 0.6
            team = await db.get(Team, task.team_id)
            n_agents = 0
            if team:
                # count agents via relationship would need extra query; use swarm_tasks assigned count fallback
                n_agents = max(1, len(votes))
                # if we have team_agents count use it
                from sqlalchemy import text
                try:
                    cnt = (await db.execute(
                        select(func.count()).select_from(
                            select(Team).where(Team.id == task.team_id).subquery()
                        )
                    )).scalar()
                    # fallback: use votes len
                except Exception:
                    pass
            approves = sum(1 for v in votes.values() if v == "approve")
            if votes and approves / len(votes) >= threshold:
                task.status = "done"
                task.result = {"consensus": "approved", "votes": votes}
                task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            elif len(votes) >= max(1, n_agents):
                # all voted but threshold not met → failed
                task.status = "failed"
                task.error = "consensus not reached"
            await db.commit()
            await db.refresh(task)
            return task

    # ── Shared memory ──

    async def put_shared(
        self, *, team_id: str, org_id: str, key: str, content: dict,
        sender_id: str | None = None, ttl_seconds: int = 3600,
         task_id: str | None = None,
    ) -> SwarmMessage:
        async with db_session() as db:
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
        self, *, team_id: str, key: str,
    ) -> SwarmMessage | None:
        async with db_session() as db:
            stmt = select(SwarmMessage).where(
                SwarmMessage.team_id == team_id,
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
        self, *, team_id: str, limit: int = 20,
    ) -> list[SwarmMessage]:
        async with db_session() as db:
            result = await db.execute(
                select(SwarmMessage).where(SwarmMessage.team_id == team_id)
                .order_by(desc(SwarmMessage.created_at)).limit(limit)
            )
            return list(result.scalars().all())

    async def stats(self, team_id: str) -> dict:
        async with db_session() as db:
            q = await db.execute(select(func.count(SwarmTask.id)).where(SwarmTask.team_id == team_id))
            total = q.scalar() or 0
            q2 = await db.execute(select(func.count(SwarmTask.id)).where(SwarmTask.team_id == team_id, SwarmTask.status == "queued"))
            queued = q2.scalar() or 0
            return {"total_tasks": total, "queued": queued}


swarm = SwarmCoordinator()
