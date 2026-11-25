"""Approval mode — human-in-the-loop for agent tool calls.

When agent autonomy is "ask_tools" or "ask_all", tool calls block
until a human approves or rejects via API.

ponytail: in-memory event dict. Swap for Redis pub/sub when multi-process.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Directly-persisted HITL rows (crm.py / team_collaboration.py) name a real
# registry tool. Alert-only Deal Desk rows are deliberately absent.
_REPLAY_TOOLS = frozenset({"crm_update_deal", "request_build"})
_AGENT_PACK_APPROVAL_TOOLS = frozenset({"agent_pack_activate", "agent_pack_rollback"})


@dataclass
class PendingAction:
    # NOTE: this in-memory dataclass shadows the identically named SQLAlchemy
    # model in aios/db/models.py. Both need org_id: the dataclass is what
    # approve()/reject() gate on, the model is what the approvals API queries.
    id: str
    org_id: str = ""
    agent_id: str = ""
    conversation_id: str = ""
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)
    context_summary: str = ""
    status: str = "pending"  # pending|approved|rejected|expired
    created_at: float = field(default_factory=time.time)
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)


class ApprovalManager:
    """Approval queue. Blocks the agent until a human decides.

    The decision itself lives in the DB, not in this process. The API process
    serves `/api/approvals/{id}/approve`; the ARQ worker holds the run. They are
    different processes, so the `asyncio.Event` alone could never be set by the
    approver — every approval timed out after the full timeout window, and the
    agent run sat blocked for 5 minutes to be told nothing.
    """

    # How often the waiter re-reads the row. Short enough to feel instant, long
    # enough not to hammer Postgres for every pending approval.
    _POLL_INTERVAL_S = 1.0

    def __init__(self, timeout: float = 300.0):
        self._pending: dict[str, PendingAction] = {}
        self._timeout = timeout

    async def request_approval(
        self,
        action_id: str,
        agent_id: str,
        conversation_id: str,
        tool_name: str,
        tool_args: dict,
        context_summary: str = "",
        org_id: str = "",
    ) -> bool:
        pa = PendingAction(
            id=action_id,
            org_id=org_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            tool_name=tool_name,
            tool_args=tool_args,
            context_summary=context_summary,
        )
        self._pending[action_id] = pa
        logger.info("Approval requested: %s for tool %s", action_id, tool_name)
        if not org_id:
            logger.warning("Approval %s has no org_id — cannot be decided safely", action_id)
        try:
            from aios.db.engine import async_session
            from aios.db.models import PendingAction as DBAction

            async with async_session() as sess:
                db_pa = DBAction(
                    id=action_id,
                    org_id=org_id,
                    agent_id=agent_id,
                    conversation_id=conversation_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    context_summary=context_summary,
                    status="pending",
                )
                sess.add(db_pa)
                await sess.commit()
        except Exception:
            logger.debug("DB approval persist failed", exc_info=True)
        try:
            from aios.core.ws_manager import ws_manager

            # broadcast() is sync — it only enqueues. Awaiting it raised
            # TypeError, which the except below swallowed, so this event
            # never reached any dashboard.
            ws_manager.broadcast(
                {
                    "type": "approval_requested",
                    "action_id": action_id,
                    "agent_id": agent_id,
                    "tool_name": tool_name,
                    "org_id": org_id,
                }
            )
        except Exception:
            logger.debug("approval broadcast failed", exc_info=True)

        try:
            await self._wait(pa)
        except (asyncio.TimeoutError, TimeoutError):
            pa.status = "expired"
            logger.warning("Approval timed out: %s", action_id)
            try:
                from aios.db.engine import async_session
                from aios.db.models import PendingAction as DBAction

                async with async_session() as sess:
                    row = await sess.get(DBAction, action_id)
                    if row and row.status == "pending":
                        row.status = "expired"
                        await sess.commit()
            except Exception:
                pass

        self._pending.pop(action_id, None)
        try:
            if pa.status != "expired":
                from aios.db.engine import async_session
                from aios.db.models import PendingAction as DBAction

                async with async_session() as sess:
                    row = await sess.get(DBAction, action_id)
                    if row:
                        row.status = pa.status
                        if pa.status in ("approved", "rejected"):
                            from datetime import datetime, timezone

                            row.decided_at = datetime.now(timezone.utc)
                        await sess.commit()
        except Exception:
            pass
        return pa.status == "approved"

    async def _wait(self, pa: PendingAction) -> None:
        """Block until this action is decided, by either path.

        The in-process `Event` is the fast path (same process, e.g. tests and
        single-process dev). The DB poll is what makes the cross-process case
        work: the approver runs in the API process and writes `status` there,
        so the worker has to look at the row, not at its own memory.
        """
        deadline = time.monotonic() + self._timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError()
            if pa.status != "pending":
                return
            try:
                await asyncio.wait_for(
                    pa._event.wait(), timeout=min(self._POLL_INTERVAL_S, remaining)
                )
                return
            except (asyncio.TimeoutError, TimeoutError):
                pass
            status = await self._db_status(pa.id)
            if status and status != "pending":
                pa.status = status
                return

    @staticmethod
    async def _db_status(action_id: str) -> str | None:
        try:
            from aios.db.engine import async_session
            from aios.db.models import PendingAction as DBAction

            async with async_session() as sess:
                row = await sess.get(DBAction, action_id)
                return row.status if row else None
        except Exception:
            return None

    async def approve(self, action_id: str, decided_by: str = "", org_id: str = "") -> bool:
        """Approve a pending action, wherever the run is waiting.

        Both halves matter. The in-process entry wakes a waiter in this process;
        the DB write is what a waiter in the *worker* process polls for. The DB
        write used to be fire-and-forget on a detached task, so the API returned
        404 "already decided" while the write was still in flight — and if the
        process was busy, the write never happened at all.
        """
        had_waiter = action_id in self._pending
        ok = await self._decide(action_id, "approved", decided_by, org_id)
        if ok and not had_waiter and action_id not in self._pending:
            await self._replay_orphan(action_id, decided_by, org_id)
        return ok

    async def reject(self, action_id: str, decided_by: str = "", org_id: str = "") -> bool:
        return await self._decide(action_id, "rejected", decided_by, org_id)

    async def _decide(
        self, action_id: str, status: str, decided_by: str, org_id: str
    ) -> bool:
        pa = self._pending.get(action_id)
        # Org gate on both paths. Without it the DB write below happily stamped
        # another tenant's row.
        if pa is not None and org_id and getattr(pa, "org_id", "") != org_id:
            logger.warning(
                "%s refused cross-org: action=%s want_org=%s actual_org=%s",
                status, action_id, org_id, getattr(pa, "org_id", ""),
            )
            return False
        wrote = await self._write_db_status(action_id, status, decided_by, org_id)
        if pa is None or pa.status != "pending":
            # No waiter in this process (the normal case: the run is in the
            # worker). The DB write is the decision.
            if not wrote:
                logger.warning(
                    "decide: no pending action %s in DB or memory — %s ignored",
                    action_id, status,
                )
            return wrote
        if not wrote:
            return False
        pa.status = status
        pa._event.set()
        logger.info("%s: %s by %s", status.capitalize(), action_id, decided_by)
        return True

    @staticmethod
    async def _replay_orphan(action_id: str, decided_by: str, org_id: str) -> None:
        """Execute an orphaned approval once, using the approver's context."""
        if not decided_by or not org_id:
            return
        try:
            import aios.tools  # noqa: F401 — populates TOOL_REGISTRY
            from sqlalchemy import select as _sel

            from aios.core.tools import ToolEngine
            from aios.db.engine import async_session as _sess
            from aios.db.models import PendingAction as DBAction
            from aios.tools.registry import TOOL_REGISTRY

            async with _sess() as sess:
                row = (await sess.execute(
                    _sel(DBAction).where(
                        DBAction.id == action_id,
                        DBAction.org_id == org_id,
                        DBAction.status == "approved",
                        DBAction.decided_by == decided_by,
                    )
                )).scalar_one_or_none()
                if not row or row.tool_name not in _REPLAY_TOOLS:
                    return
                if row.tool_name not in TOOL_REGISTRY:
                    return
                raw_args = row.tool_args
                if not isinstance(raw_args, dict):
                    return
                # Caller-supplied marker is untrusted; DB row is authoritative.
                args = dict(raw_args)
                args.pop("_requested_by", None)
                args["_hitl_approved_action"] = {
                    "action_id": row.id,
                    "org_id": row.org_id,
                    "decided_by": row.decided_by,
                }
                tool_name = row.tool_name
                agent_id = row.agent_id or ""

            engine = ToolEngine(
                [tool_name], org_id=org_id, agent_id=agent_id,
                actor_user_id=decided_by,
            )
            await engine.execute(tool_name, json.dumps(args))
            logger.info("Replayed approved action %s via %s", action_id, tool_name)
        except Exception:
            logger.exception("approval replay failed for %s", action_id)

    @staticmethod
    async def _write_db_status(
        action_id: str, status: str, decided_by: str, org_id: str
    ) -> bool:
        from datetime import datetime, timezone

        from sqlalchemy import update as _upd

        from aios.db.engine import async_session as _sess
        from aios.db.models import PendingAction as DBAction

        try:
            async with _sess() as sess:
                # Conditional UPDATE is the compare-and-set: concurrent
                # approvers cannot both flip the same pending row.
                stmt = (
                    _upd(DBAction)
                    .where(DBAction.id == action_id, DBAction.status == "pending")
                    .values(
                        status=status,
                        decided_by=decided_by,
                        decided_at=datetime.now(timezone.utc),
                    )
                )
                if org_id:
                    stmt = stmt.where(DBAction.org_id == org_id)
                result = await sess.execute(stmt)
                if result.rowcount != 1:
                    return False
                await sess.commit()
                return True
        except Exception:
            logger.exception("decide: could not write %s for %s", status, action_id)
            return False

    def get_pending(self, agent_id: str = "", org_id: str = "") -> list[dict]:
        result = []
        for pa in self._pending.values():
            if pa.status != "pending":
                continue
            if agent_id and pa.agent_id != agent_id:
                continue
            if org_id and getattr(pa, "org_id", "") != org_id:
                continue
            result.append(
                {
                    "id": pa.id,
                    "agent_id": pa.agent_id,
                    "conversation_id": pa.conversation_id,
                    "tool_name": pa.tool_name,
                    "tool_args": pa.tool_args,
                    "context_summary": pa.context_summary,
                    "status": pa.status,
                    "created_at": pa.created_at,
                }
            )
        return result

    def cancel_expired(self) -> int:
        """Mark stale actions as expired."""
        now = time.time()
        expired = 0
        for pa in list(self._pending.values()):
            if pa.status == "pending" and now - pa.created_at > self._timeout:
                pa.status = "expired"
                pa._event.set()
                expired += 1
        return expired


# Global instance
approval_manager = ApprovalManager()
