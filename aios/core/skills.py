"""Skill store — persist and retrieve reusable agent patterns.

Skills are extracted from successful tool execution sequences.
They're searchable, versioned by usage_count, and injectable into context.
"""

import logging
from sqlalchemy import select, update

from aios.core.content_scan import check_store_text
from aios.db.backend import db_session
from aios.db.models import Skill

logger = logging.getLogger(__name__)


class SkillStore:
    """CRUD + search for skills. DB-backed."""

    async def exists(self, *, agent_id: str, org_id: str, name: str) -> bool:
        """Targeted name check (the auto-extractor's dedup; list() pages)."""
        async with db_session() as db:
            stmt = select(Skill.id).where(
                Skill.agent_id == agent_id, Skill.name == name,
            )
            if org_id:
                stmt = stmt.where(Skill.org_id == org_id)
            return (await db.execute(stmt.limit(1))).first() is not None

    async def create(self, *, agent_id: str, org_id: str, name: str,
                     description: str = "", skill_type: str = "tool_pattern",
                     content: str = "", input_schema: dict = None,
                     tags: list[str] = None, source_conversation_id: str = None) -> Skill:
        # Stored content is re-injected into future prompts, so scan at the
        # store: a refused write raises here (dashboard/API surface it), while
        # the fire-and-forget auto-extractor just drops that row.
        scanned = check_store_text(content or "", source=f"skill:{name}")
        if scanned is None:
            raise ValueError(f"skill content rejected by store scan: {name}")
        content = scanned
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

    async def get(self, skill_id: str, org_id: str = "") -> Skill | None:
        # org_id is mandatory for tenant safety: Skill.content is prompt text, so
        # an unscoped read hands another tenant's injected instructions to the
        # caller. Empty org_id means "no filter" and is only used by callers that
        # have already validated the row themselves.
        async with db_session() as db:
            stmt = select(Skill).where(Skill.id == skill_id)
            if org_id:
                stmt = stmt.where(Skill.org_id == org_id)
            result = await db.execute(stmt)
            return result.scalar_one_or_none()

    async def list(self, agent_id: str = "", q: str = "", limit: int = 50, org_id: str = "") -> list[Skill]:
        async with db_session() as db:
            stmt = select(Skill)
            if org_id:
                stmt = stmt.where(Skill.org_id == org_id)
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

    async def update(self, skill_id: str, org_id: str = "", **fields) -> Skill | None:
        if "content" in fields:
            scanned = check_store_text(fields["content"] or "", source=f"skill:{skill_id}")
            if scanned is None:
                raise ValueError("skill content rejected by store scan")
            fields = {**fields, "content": scanned}
        async with db_session() as db:
            stmt = update(Skill).where(Skill.id == skill_id)
            if org_id:
                stmt = stmt.where(Skill.org_id == org_id)
            res = await db.execute(stmt.values(**fields))
            await db.commit()
            if res.rowcount == 0:
                return None
            return await self.get(skill_id, org_id=org_id)

    async def delete(self, skill_id: str, org_id: str = "") -> bool:
        async with db_session() as db:
            stmt = select(Skill).where(Skill.id == skill_id)
            if org_id:
                stmt = stmt.where(Skill.org_id == org_id)
            skill = (await db.execute(stmt)).scalar_one_or_none()
            if not skill:
                return False
            await db.delete(skill)
            await db.commit()
            return True

    async def increment_usage(self, skill_id: str, org_id: str = "") -> None:
        async with db_session() as db:
            stmt = update(Skill).where(Skill.id == skill_id)
            if org_id:
                stmt = stmt.where(Skill.org_id == org_id)
            await db.execute(stmt.values(usage_count=Skill.usage_count + 1))
            await db.commit()


skill_store = SkillStore()
