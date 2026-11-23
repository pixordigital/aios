"""Swarm coordinator — leader/worker, task distribution, consensus, shared memory.

Ruflo swarm pattern: agents self-organize, distribute tasks, vote, share memory.
Backed by team_swarm_configs + swarm_tasks + swarm_messages tables.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Generic, TypeVar

from sqlalchemy import select, desc, func

from aios.db.backend import db_session
from aios.db.models import Agent, Conversation, SwarmMessage, SwarmTask, Team, TeamSwarmConfig, team_agents

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class SwarmScopedResult(Generic[T]):
    """Explicit scope/query outcome. ok=False means no tenant data exposed."""

    ok: bool
    reason: str = "ok"
    value: T | None = None

    @classmethod
    def denied(cls, reason: str) -> "SwarmScopedResult[T]":
        return cls(ok=False, reason=reason, value=None)

    @classmethod
    def success(cls, value: T) -> "SwarmScopedResult[T]":
        return cls(ok=True, reason="ok", value=value)

_SWARM_MODES = {"supervisor", "consensus", "pipeline", "mesh"}
_TERMINAL_TASK_STATUSES = {"done", "failed"}
_ACTIVE_TASK_STATUSES = {"queued", "assigned", "running", "consensus"}
_VALID_VOTES = {"approve", "reject", "abstain"}
_IDEMPOTENCY_SCAN_LIMIT = 200
_IDEMPOTENCY_KEY_MAX = 128


def _normalize_idempotency_key(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    key = raw.strip()
    if not key or len(key) > _IDEMPOTENCY_KEY_MAX:
        return None
    return key


def _task_idempotency_key(task: SwarmTask) -> str | None:
    for src in (getattr(task, "payload", None), getattr(task, "extra_data", None)):
        if isinstance(src, dict):
            key = _normalize_idempotency_key(src.get("idempotency_key"))
            if key:
                return key
    return None


def _select_for_update(db, stmt):
    bind = None
    getter = getattr(db, "get_bind", None)
    if callable(getter):
        bind = getter()
    else:
        sess = getattr(db, "_session", None)
        bind = getattr(sess, "bind", None)
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect == "sqlite":
        return stmt
    return stmt.with_for_update()


async def _lock_team_dispatch(db, team_id: str, org_id: str) -> bool:
    """Best-effort dispatch serializer. PG: row lock on team; SQLite: no-op lock, still fail-closed on ownership."""
    stmt = select(Team.id).where(Team.id == team_id, Team.org_id == org_id)
    stmt = _select_for_update(db, stmt)
    return (await db.execute(stmt)).scalar_one_or_none() is not None


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
        agent_id: str | None = None, idempotency_key: str | None = None,
    ) -> SwarmTask | None:
        """Queue a task for swarm execution. Fail closed on org/team/membership/ownership mismatch.

        Idempotency: normalized key from explicit arg or payload.idempotency_key.
        Same team/org/task_type/key returns existing task (active or terminal) instead of duplicating.
        Best-effort only, no unique index/migration: PG row lock helps; SQLite has race window.
        """
        if not team_id or not org_id or not isinstance(task_type, str) or not task_type.strip():
            return None
        task_type = task_type.strip()
        async with db_session() as db:
            if not await _lock_team_dispatch(db, team_id, org_id):
                return None
            if agent_id and not await _agent_in_team(db, agent_id, team_id, org_id):
                return None
            if conversation_id and not await _conversation_in_scope(
                db, conversation_id, team_id=team_id, org_id=org_id
            ):
                return None
            deps = [d for d in (depends_on or []) if isinstance(d, str) and d]
            if not await _depends_on_valid(db, deps, team_id=team_id, org_id=org_id):
                return None

            payload_data = dict(payload or {})
            explicit_idem = _normalize_idempotency_key(idempotency_key)
            payload_idem = _normalize_idempotency_key(payload_data.get("idempotency_key"))
            idem = explicit_idem or payload_idem
            if explicit_idem:
                payload_data["idempotency_key"] = explicit_idem
            elif payload_idem:
                payload_data["idempotency_key"] = payload_idem

            if idem:
                existing_stmt = select(SwarmTask).where(
                    SwarmTask.team_id == team_id,
                    SwarmTask.org_id == org_id,
                    SwarmTask.task_type == task_type,
                ).order_by(desc(SwarmTask.created_at)).limit(_IDEMPOTENCY_SCAN_LIMIT)
                existing_stmt = _select_for_update(db, existing_stmt)
                for row in (await db.execute(existing_stmt)).scalars().all():
                    if _task_idempotency_key(row) == idem:
                        logger.info(
                            "swarm.dispatch idempotency hit team=%s org=%s type=%s key=%s task=%s",
                            team_id, org_id, task_type, idem, row.id,
                        )
                        return row

            task = SwarmTask(
                team_id=team_id, org_id=org_id, task_id=str(uuid.uuid4())[:16],
                task_type=task_type, payload=payload_data, priority=int(priority or 0),
                conversation_id=conversation_id, depends_on=deps,
                assigned_agent_id=agent_id, status="queued" if not agent_id else "assigned",
            )
            db.add(task)
            await db.flush()
            if idem:
                recheck_stmt = select(SwarmTask).where(
                    SwarmTask.team_id == team_id,
                    SwarmTask.org_id == org_id,
                    SwarmTask.task_type == task_type,
                    SwarmTask.id != task.id,
                ).order_by(desc(SwarmTask.created_at)).limit(_IDEMPOTENCY_SCAN_LIMIT)
                recheck_stmt = _select_for_update(db, recheck_stmt)
                for row in (await db.execute(recheck_stmt)).scalars().all():
                    if _task_idempotency_key(row) == idem:
                        await db.delete(task)
                        await db.commit()
                        logger.warning(
                            "swarm.dispatch idempotency race resolved team=%s org=%s type=%s key=%s kept=%s dropped=%s",
                            team_id, org_id, task_type, idem, row.id, task.id,
                        )
                        return row
            await db.commit()
            await db.refresh(task)
            return task

    async def claim(self, task_id: str, agent_id: str, org_id: str, team_id: str = "") -> SwarmTask | None:
        if not task_id or not agent_id or not org_id:
            return None
        async with db_session() as db:
            stmt = select(SwarmTask).where(SwarmTask.id == task_id)
            stmt = _select_for_update(db, stmt)
            task = (await db.execute(stmt)).scalar_one_or_none()
            if not task or task.org_id != org_id:
                # Fail closed: cross-tenant/missing reads as missing.
                return None
            if team_id and task.team_id != team_id:
                return None
            if task.status not in ("queued", "assigned"):
                return None
            if not await _agent_in_team(db, agent_id, task.team_id, org_id):
                logger.info(
                    "swarm.claim rejected: agent not in team task=%s team=%s agent=%s org=%s",
                    task_id, task.team_id, agent_id, org_id,
                )
                return None
            task.assigned_agent_id = agent_id
            task.status = "running"
            task.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
            task.attempts = int(task.attempts or 0) + 1
            await db.commit()
            await db.refresh(task)
            return task

    async def complete(
        self, task_id: str, result: dict | None = None, error: str = "", org_id: str = "", team_id: str = "",
    ) -> SwarmTask | None:
        if not task_id or not org_id:
            # Fail closed: org_id required for mutating completion.
            return None
        async with db_session() as db:
            stmt = select(SwarmTask).where(SwarmTask.id == task_id)
            stmt = _select_for_update(db, stmt)
            task = (await db.execute(stmt)).scalar_one_or_none()
            if not task or task.org_id != org_id:
                return None
            if team_id and task.team_id != team_id:
                return None

            requested_status = "failed" if error else "done"
            if task.status in _TERMINAL_TASK_STATUSES:
                # Idempotent same-status completion; reject terminal overwrite/conflict.
                if task.status == requested_status:
                    return task
                logger.info(
                    "swarm.complete conflict task=%s org=%s cur=%s req=%s",
                    task_id, org_id, task.status, requested_status,
                )
                return None
            if task.status not in _ACTIVE_TASK_STATUSES:
                return None

            task.result = result if isinstance(result, dict) else {}
            task.error = str(error or "")
            task.status = requested_status
            task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.commit()
            await db.refresh(task)
            return task

    async def get_task(
        self, task_id: str, *, org_id: str, team_id: str = ""
    ) -> SwarmTask | None:
        """Org/team-scoped task lookup for API conflict vs not-found mapping."""
        async with db_session() as db:
            if not org_id:
                return None
            stmt = select(SwarmTask).where(SwarmTask.id == task_id, SwarmTask.org_id == org_id)
            if team_id:
                stmt = stmt.where(SwarmTask.team_id == team_id)
            return (await db.execute(stmt)).scalar_one_or_none()

    async def _team_scope_reason(self, db, team_id: str, org_id: str) -> str | None:
        if not org_id:
            return "missing_org"
        if not team_id:
            return "missing_team"
        if not await _team_belongs_to_org(db, team_id, org_id):
            return "team_not_found"
        return None

    async def inspect_team_scope(self, team_id: str, org_id: str) -> SwarmScopedResult[None]:
        async with db_session() as db:
            reason = await self._team_scope_reason(db, team_id, org_id)
        if reason:
            return SwarmScopedResult.denied(reason)
        return SwarmScopedResult.success(None)

    async def list_tasks_result(
        self, *, team_id: str, status: str = "", limit: int = 20, org_id: str = "",
    ) -> SwarmScopedResult[list[SwarmTask]]:
        async with db_session() as db:
            reason = await self._team_scope_reason(db, team_id, org_id)
            if reason:
                return SwarmScopedResult.denied(reason)
            stmt = select(SwarmTask).where(SwarmTask.team_id == team_id, SwarmTask.org_id == org_id)
            if status:
                stmt = stmt.where(SwarmTask.status == status)
            stmt = stmt.order_by(desc(SwarmTask.priority), desc(SwarmTask.created_at)).limit(limit)
            result = await db.execute(stmt)
            return SwarmScopedResult.success(list(result.scalars().all()))

    async def list_tasks(
        self, *, team_id: str, status: str = "", limit: int = 20, org_id: str = "",
    ) -> list[SwarmTask]:
        scoped = await self.list_tasks_result(team_id=team_id, status=status, limit=limit, org_id=org_id)
        return scoped.value if scoped.ok and scoped.value is not None else []

    # ── Consensus ──

    async def vote(self, task_id: str, agent_id: str, vote: str, org_id: str = "", team_id: str = "") -> SwarmTask | None:
        """Record a consensus vote (approve|reject|abstain). Check threshold if reached."""
        if not task_id or not agent_id or not org_id:
            return None
        vote_norm = vote.strip().lower() if isinstance(vote, str) else ""
        if vote_norm not in _VALID_VOTES:
            return None
        async with db_session() as db:
            stmt = select(SwarmTask).where(SwarmTask.id == task_id)
            stmt = _select_for_update(db, stmt)
            task = (await db.execute(stmt)).scalar_one_or_none()
            if not task or task.org_id != org_id:
                return None
            if team_id and task.team_id != team_id:
                return None
            if not await _agent_in_team(db, agent_id, task.team_id, task.org_id):
                return None

            if task.status in _TERMINAL_TASK_STATUSES:
                votes = dict(task.consensus_votes or {})
                if votes.get(agent_id) == vote_norm:
                    return task
                return None
            if task.status not in _ACTIVE_TASK_STATUSES:
                return None

            votes = dict(task.consensus_votes or {})
            votes[agent_id] = vote_norm
            task.consensus_votes = votes
            # check threshold
            cfg = (
                await db.execute(
                    select(TeamSwarmConfig).where(
                        TeamSwarmConfig.team_id == task.team_id,
                        TeamSwarmConfig.org_id == task.org_id,
                    )
                )
            ).scalar_one_or_none()
            threshold = cfg.consensus_threshold if cfg else 0.6
            try:
                threshold = float(threshold)
            except (TypeError, ValueError):
                threshold = 0.6
            threshold = min(1.0, max(0.0, threshold))
            n_agents = await _team_member_count(db, task.team_id, task.org_id)
            if n_agents <= 0:
                task.status = "failed"
                task.error = "consensus denominator unavailable"
                task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                logger.warning("swarm.vote failed: no team members task=%s team=%s org=%s", task_id, task.team_id, org_id)
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
                task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
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

    async def list_messages_result(
        self, *, team_id: str, limit: int = 20, org_id: str = "",
    ) -> SwarmScopedResult[list[SwarmMessage]]:
        async with db_session() as db:
            reason = await self._team_scope_reason(db, team_id, org_id)
            if reason:
                return SwarmScopedResult.denied(reason)
            result = await db.execute(
                select(SwarmMessage).where(
                    SwarmMessage.team_id == team_id,
                    SwarmMessage.org_id == org_id,
                )
                .order_by(desc(SwarmMessage.created_at)).limit(limit)
            )
            return SwarmScopedResult.success(list(result.scalars().all()))

    async def list_messages(
        self, *, team_id: str, limit: int = 20, org_id: str = "",
    ) -> list[SwarmMessage]:
        scoped = await self.list_messages_result(team_id=team_id, limit=limit, org_id=org_id)
        return scoped.value if scoped.ok and scoped.value is not None else []

    async def stats_result(self, team_id: str, org_id: str = "") -> SwarmScopedResult[dict]:
        async with db_session() as db:
            reason = await self._team_scope_reason(db, team_id, org_id)
            if reason:
                return SwarmScopedResult.denied(reason)
            base = [SwarmTask.team_id == team_id, SwarmTask.org_id == org_id]
            q = await db.execute(select(func.count(SwarmTask.id)).where(*base))
            total = q.scalar() or 0
            q2 = await db.execute(select(func.count(SwarmTask.id)).where(*base, SwarmTask.status == "queued"))
            queued = q2.scalar() or 0
            return SwarmScopedResult.success({"total_tasks": total, "queued": queued})

    async def stats(self, team_id: str, org_id: str = "") -> dict:
        scoped = await self.stats_result(team_id, org_id=org_id)
        return scoped.value if scoped.ok and scoped.value is not None else {"total_tasks": 0, "queued": 0}


swarm = SwarmCoordinator()
