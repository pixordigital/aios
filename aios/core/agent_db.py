"""AgentDB — persistent cross-session knowledge + learning + reflection store.

Ruflo AgentDB pattern: agents learn from every task, remember across sessions,
reuse successful patterns. This module is the harness memory layer.
"""

import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy import select, desc, func, update

from aios.db.backend import db_session
from aios.db.models import AgentKnowledge, AgentLearning, AgentReflection

logger = logging.getLogger(__name__)


def _pattern_sig(trigger: str, action: str) -> str:
    raw = f"{trigger}|{action}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


class AgentDB:
    """CRUD + vector search for agent knowledge, learnings, reflections."""

    # ── Knowledge ──

    async def put_knowledge(
        self, *, agent_id: str, org_id: str, knowledge_type: str,
        key: str, value: str, confidence: float = 1.0, source: str = "agent",
        tags: list[str] | None = None, embedding: list[float] | None = None,
        expires_at: datetime | None = None, extra_data: dict | None = None,
    ) -> AgentKnowledge:
        async with db_session() as db:
            row = AgentKnowledge(
                agent_id=agent_id, org_id=org_id, knowledge_type=knowledge_type,
                key=key, value=value, confidence=confidence, source=source,
                tags=tags or [], embedding=embedding, expires_at=expires_at,
                extra_data=extra_data or {},
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return row

    async def get_knowledge(self, knowledge_id: str) -> AgentKnowledge | None:
        async with db_session() as db:
            return await db.get(AgentKnowledge, knowledge_id)

    async def search_knowledge(
        self, *, org_id: str, agent_id: str = "", q: str = "",
        knowledge_type: str = "", limit: int = 20,
    ) -> list[AgentKnowledge]:
        async with db_session() as db:
            stmt = select(AgentKnowledge).where(AgentKnowledge.org_id == org_id)
            if agent_id:
                stmt = stmt.where(AgentKnowledge.agent_id == agent_id)
            if knowledge_type:
                stmt = stmt.where(AgentKnowledge.knowledge_type == knowledge_type)
            if q:
                pat = f"%{q.lower()}%"
                stmt = stmt.where(
                    AgentKnowledge.key.ilike(pat) | AgentKnowledge.value.ilike(pat)
                )
            stmt = stmt.order_by(desc(AgentKnowledge.confidence), desc(AgentKnowledge.created_at)).limit(limit)
            result = await db.execute(stmt)
            return list(result.scalars().all())

    async def similar_knowledge(
        self, *, org_id: str, agent_id: str, query_text: str, limit: int = 5,
    ) -> list[AgentKnowledge]:
        """Keyword-based similarity (upgrade to vector cosine when embeddings present)."""
        return await self.search_knowledge(org_id=org_id, agent_id=agent_id, q=query_text, limit=limit)

    async def bump_knowledge_usage(self, knowledge_id: str) -> None:
        async with db_session() as db:
            await db.execute(
                update(AgentKnowledge).where(AgentKnowledge.id == knowledge_id).values(
                    usage_count=AgentKnowledge.usage_count + 1,
                    last_accessed=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
            await db.commit()

    # ── Learnings ──

    async def record_learning(
        self, *, agent_id: str, org_id: str, learning_type: str,
        trigger_context: str, action_taken: str, outcome: str,
        success: bool = True, metrics: dict | None = None, confidence: float = 1.0,
        tags: list[str] | None = None, extra_data: dict | None = None,
    ) -> AgentLearning:
        sig = _pattern_sig(trigger_context, action_taken)
        async with db_session() as db:
            row = AgentLearning(
                agent_id=agent_id, org_id=org_id, learning_type=learning_type,
                trigger_context=trigger_context, action_taken=action_taken,
                outcome=outcome, success=success, metrics=metrics or {},
                pattern_signature=sig, confidence=confidence,
                tags=tags or [], extra_data=extra_data or {},
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return row

    async def list_learnings(
        self, *, org_id: str, agent_id: str = "", learning_type: str = "",
        success: bool | None = None, limit: int = 20,
    ) -> list[AgentLearning]:
        async with db_session() as db:
            stmt = select(AgentLearning).where(AgentLearning.org_id == org_id)
            if agent_id:
                stmt = stmt.where(AgentLearning.agent_id == agent_id)
            if learning_type:
                stmt = stmt.where(AgentLearning.learning_type == learning_type)
            if success is not None:
                stmt = stmt.where(AgentLearning.success == success)
            stmt = stmt.order_by(desc(AgentLearning.created_at)).limit(limit)
            result = await db.execute(stmt)
            return list(result.scalars().all())

    async def top_patterns(self, *, org_id: str, agent_id: str = "", limit: int = 10) -> list[AgentLearning]:
        async with db_session() as db:
            stmt = select(AgentLearning).where(
                AgentLearning.org_id == org_id, AgentLearning.success.is_(True)
            )
            if agent_id:
                stmt = stmt.where(AgentLearning.agent_id == agent_id)
            stmt = stmt.order_by(desc(AgentLearning.applied_count), desc(AgentLearning.confidence)).limit(limit)
            result = await db.execute(stmt)
            return list(result.scalars().all())

    # ── Reflections ──

    async def create_reflection(
        self, *, agent_id: str, org_id: str, conversation_id: str | None = None,
        task_summary: str = "", what_went_well: str = "", what_could_improve: str = "",
        key_insight: str = "", action_items: list[str] | None = None,
        score: float = 0.0, tokens_used: int = 0, extra_data: dict | None = None,
    ) -> AgentReflection:
        async with db_session() as db:
            row = AgentReflection(
                agent_id=agent_id, org_id=org_id, conversation_id=conversation_id,
                task_summary=task_summary, what_went_well=what_went_well,
                what_could_improve=what_could_improve, key_insight=key_insight,
                action_items=action_items or [], score=score, tokens_used=tokens_used,
                extra_data=extra_data or {},
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return row

    async def list_reflections(
        self, *, org_id: str, agent_id: str = "", limit: int = 20,
    ) -> list[AgentReflection]:
        async with db_session() as db:
            stmt = select(AgentReflection).where(AgentReflection.org_id == org_id)
            if agent_id:
                stmt = stmt.where(AgentReflection.agent_id == agent_id)
            stmt = stmt.order_by(desc(AgentReflection.created_at)).limit(limit)
            result = await db.execute(stmt)
            return list(result.scalars().all())

    # ── Stats ──

    async def stats(self, *, org_id: str, agent_id: str = "") -> dict:
        async with db_session() as db:
            q = {"org_id": org_id}
            if agent_id:
                q["agent_id"] = agent_id
            k_cnt = (await db.execute(select(func.count(AgentKnowledge.id)).where(AgentKnowledge.org_id == org_id))).scalar() or 0
            l_cnt = (await db.execute(select(func.count(AgentLearning.id)).where(AgentLearning.org_id == org_id))).scalar() or 0
            r_cnt = (await db.execute(select(func.count(AgentReflection.id)).where(AgentReflection.org_id == org_id))).scalar() or 0
            return {"knowledge": k_cnt, "learnings": l_cnt, "reflections": r_cnt}


agent_db = AgentDB()
