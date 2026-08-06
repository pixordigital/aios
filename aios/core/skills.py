"""Skill store — persist and retrieve reusable agent patterns.

Skills are extracted from successful tool execution sequences.
They're searchable, versioned by usage_count, and injectable into context.
"""

import logging
from sqlalchemy import select, update

from aios.db.backend import db_session
from aios.db.models import Skill

logger = logging.getLogger(__name__)


class SkillStore:
    """CRUD + search for skills. DB-backed."""

    async def create(self, *, agent_id: str, org_id: str, name: str,
                     description: str = "", skill_type: str = "tool_pattern",
                     content: str = "", input_schema: dict = None,
                     tags: list[str] = None, source_conversation_id: str = None) -> Skill:
        async with db_session() as db:
            skill = Skill(
                agent_id=agent_id,
                org_id=org_id,
                name=name,
                description=description,
                skill_type=skill_type,
                content=content,
                input_schema=input_schema or {},
                tags=tags or [],
                source_conversation_id=source_conversation_id,
            )
            db.add(skill)
            await db.commit()
            await db.refresh(skill)
            return skill

    async def get(self, skill_id: str) -> Skill | None:
        async with db_session() as db:
            result = await db.execute(select(Skill).where(Skill.id == skill_id))
            return result.scalar_one_or_none()

    async def list(self, agent_id: str = "", q: str = "", limit: int = 50) -> list[Skill]:
        async with db_session() as db:
            stmt = select(Skill)
            if agent_id:
                stmt = stmt.where(Skill.agent_id == agent_id)
            if q:
                lower_q = f"%{q.lower()}%"
                stmt = stmt.where(
                    Skill.name.ilike(lower_q) | Skill.description.ilike(lower_q)
                )
            stmt = stmt.order_by(Skill.usage_count.desc()).limit(limit)
            result = await db.execute(stmt)
            return list(result.scalars().all())

    async def update(self, skill_id: str, **fields) -> Skill | None:
        async with db_session() as db:
            await db.execute(update(Skill).where(Skill.id == skill_id).values(**fields))
            await db.commit()
            return await self.get(skill_id)

    async def delete(self, skill_id: str) -> bool:
        async with db_session() as db:
            skill = await db.get(Skill, skill_id)
            if not skill:
                return False
            await db.delete(skill)
            await db.commit()
            return True

    async def increment_usage(self, skill_id: str) -> None:
        async with db_session() as db:
            await db.execute(
                update(Skill).where(Skill.id == skill_id)
                .values(usage_count=Skill.usage_count + 1)
            )
            await db.commit()


skill_store = SkillStore()
