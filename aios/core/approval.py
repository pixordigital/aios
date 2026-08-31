"""Approval mode — human-in-the-loop for agent tool calls.

When agent autonomy is "ask_tools" or "ask_all", tool calls block
until a human approves or rejects via API.

ponytail: in-memory event dict. Swap for Redis pub/sub when multi-process.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PendingAction:
    id: str
    agent_id: str
    conversation_id: str
    tool_name: str
    tool_args: dict
    context_summary: str = ""
    status: str = "pending"  # pending|approved|rejected|expired
    created_at: float = field(default_factory=time.time)
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)


class ApprovalManager:
    """In-memory approval queue. Blocks agent until human decides."""

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
    ) -> bool:
        pa = PendingAction(
            id=action_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            tool_name=tool_name,
            tool_args=tool_args,
            context_summary=context_summary,
        )
        self._pending[action_id] = pa
        logger.info("Approval requested: %s for tool %s", action_id, tool_name)
        try:
            from aios.db.engine import async_session
            from aios.db.models import PendingAction as DBAction

            async with async_session() as sess:
                db_pa = DBAction(
                    id=action_id,
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

            await ws_manager.broadcast(
                {
                    "type": "approval_requested",
                    "action_id": action_id,
                    "agent_id": agent_id,
                    "tool_name": tool_name,
                }
            )
        except Exception:
            pass

        try:
            await asyncio.wait_for(pa._event.wait(), timeout=self._timeout)
        except (asyncio.TimeoutError, TimeoutError):
            pa.status = "expired"
            logger.warning("Approval timed out: %s", action_id)
            try:
                from aios.db.engine import async_session
                from aios.db.models import PendingAction as DBAction

                async with async_session() as sess:
                    db_pa = await sess.get(DBAction, action_id)
                    if db_pa and db_pa.status == "pending":
                        db_pa.status = "expired"
                        await sess.commit()
            except Exception:
                pass

        self._pending.pop(action_id, None)
        try:
            if pa.status != "expired":
                from aios.db.engine import async_session
                from aios.db.models import PendingAction as DBAction

                async with async_session() as sess:
                    db_pa = await sess.get(DBAction, action_id)
                    if db_pa:
                        db_pa.status = pa.status
                        if pa.status in ("approved", "rejected"):
                            from datetime import datetime, timezone

                            db_pa.decided_at = datetime.now(timezone.utc)
                        await sess.commit()
        except Exception:
            pass
        return pa.status == "approved"

    def approve(self, action_id: str, decided_by: str = "") -> bool:
        pa = self._pending.get(action_id)
        if not pa or pa.status != "pending":
            try:
                import asyncio as _asyncio

                from aios.db.engine import async_session as _sess
                from aios.db.models import PendingAction as DBAction

                async def _db_approve():
                    async with _sess() as sess:
                        db_pa = await sess.get(DBAction, action_id)
                        if db_pa and db_pa.status == "pending":
                            db_pa.status = "approved"
                            db_pa.decided_by = decided_by
                            from datetime import datetime, timezone

                            db_pa.decided_at = datetime.now(timezone.utc)
                            await sess.commit()
                            return True
                    return False

                try:
                    loop = _asyncio.get_running_loop()
                    loop.create_task(_db_approve())
                except RuntimeError:
                    pass
            except Exception:
                pass
            return False
        pa.status = "approved"
        pa._event.set()
        logger.info("Approved: %s by %s", action_id, decided_by)
        return True

    def reject(self, action_id: str, decided_by: str = "") -> bool:
        pa = self._pending.get(action_id)
        if not pa or pa.status != "pending":
            return False
        pa.status = "rejected"
        pa._event.set()
        logger.info("Rejected: %s by %s", action_id, decided_by)
        return True

    def get_pending(self, agent_id: str = "") -> list[dict]:
        result = []
        for pa in self._pending.values():
            if pa.status != "pending":
                continue
            if agent_id and pa.agent_id != agent_id:
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
