"""Library — unified search across artifacts, skills, and messages.

Cross-table search with relevance ranking.
"""

import logging
from sqlalchemy import select, or_, func

from aios.db.backend import db_session
from aios.db.models import Artifact, Skill, Message

logger = logging.getLogger(__name__)


class LibraryIndex:
    """Search across artifacts, skills, and messages."""

    async def search(self, query: str, org_id: str,
                     item_type: str = "", limit: int = 20) -> list[dict]:
        """Search across all content types.

        item_type: "artifact" | "skill" | "message" | "" (all)
        """
        results = []
        lower_q = f"%{query.lower()}%"

        async with db_session() as db:
            if item_type in ("", "artifact"):
                stmt = select(Artifact).where(
                    Artifact.org_id == org_id,
                    or_(
                        Artifact.filename.ilike(lower_q),
                        Artifact.description.ilike(lower_q),
                        Artifact.searchable_content.ilike(lower_q),
                    )
                ).limit(limit)
                for art in (await db.execute(stmt)).scalars().all():
                    results.append({
                        "type": "artifact",
                        "id": art.id,
                        "title": art.filename,
                        "description": art.description[:200],
                        "created_at": str(art.created_at) if art.created_at else "",
                    })

            if item_type in ("", "skill"):
                stmt = select(Skill).where(
                    Skill.org_id == org_id,
                    or_(
                        Skill.name.ilike(lower_q),
                        Skill.description.ilike(lower_q),
                    )
                ).limit(limit)
                for sk in (await db.execute(stmt)).scalars().all():
                    results.append({
                        "type": "skill",
                        "id": sk.id,
                        "title": sk.name,
                        "description": sk.description[:200],
                        "created_at": str(sk.created_at) if sk.created_at else "",
                    })

            if item_type in ("", "message"):
                stmt = select(Message).where(
                    Message.org_id == org_id,
                    Message.content.ilike(lower_q),
                ).order_by(Message.created_at.desc()).limit(limit)
                for msg in (await db.execute(stmt)).scalars().all():
                    results.append({
                        "type": "message",
                        "id": msg.id,
                        "title": f"{msg.role}: {msg.content[:80]}",
                        "description": msg.content[:200],
                        "created_at": str(msg.created_at) if msg.created_at else "",
                    })

        return results[:limit]

    async def recent(self, org_id: str, limit: int = 20) -> list[dict]:
        """Get most recent items across all types."""
        results = []
        async with db_session() as db:
            # artifacts
            stmt = select(Artifact).where(Artifact.org_id == org_id).order_by(Artifact.created_at.desc()).limit(limit // 3)
            for art in (await db.execute(stmt)).scalars().all():
                results.append({"type": "artifact", "id": art.id, "title": art.filename, "created_at": str(art.created_at) if art.created_at else ""})
            # skills
            stmt = select(Skill).where(Skill.org_id == org_id).order_by(Skill.created_at.desc()).limit(limit // 3)
            for sk in (await db.execute(stmt)).scalars().all():
                results.append({"type": "skill", "id": sk.id, "title": sk.name, "created_at": str(sk.created_at) if sk.created_at else ""})
            # messages
            stmt = select(Message).where(Message.org_id == org_id).order_by(Message.created_at.desc()).limit(limit // 3)
            for msg in (await db.execute(stmt)).scalars().all():
                results.append({"type": "message", "id": msg.id, "title": msg.content[:80], "created_at": str(msg.created_at) if msg.created_at else ""})

        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return results[:limit]

    async def stats(self, org_id: str) -> dict:
        """Count items per type."""
        async with db_session() as db:
            artifacts = (await db.execute(select(func.count()).select_from(Artifact).where(Artifact.org_id == org_id))).scalar() or 0
            skills = (await db.execute(select(func.count()).select_from(Skill).where(Skill.org_id == org_id))).scalar() or 0
            messages = (await db.execute(select(func.count()).select_from(Message).where(Message.org_id == org_id))).scalar() or 0
        return {"artifacts": artifacts, "skills": skills, "messages": messages}


library = LibraryIndex()
