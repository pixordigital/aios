"""Read Skill Tool — load one stored skill's full content at runtime.

The run loop injects DB skills as name + description only (cheap index), so
without this the agent could see a skill exists but never read what it says —
a catalogue with no books. This is the `skill_view` half of that loop.
"""

import logging

from sqlalchemy.exc import SQLAlchemyError

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)

_MAX_CHARS = 6000


class ReadSkillTool(BaseTool):
    name = "read_skill"
    description = (
        "Read the full content of one stored skill by name or id "
        "(e.g. after seeing it in the Relevant skills list). "
        "Returns the procedure, pitfalls and verification steps."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name or id, e.g. 'auto:crm_list_deals'"},
        },
        "required": ["name"],
    }

    async def run(self, name: str) -> dict:
        try:
            from aios.core.skills import skill_store

            org_id = getattr(self, "_org_id", "") or ""
            agent_id = getattr(self, "_agent_id", "") or ""
            skill = await skill_store.get(name, org_id=org_id)
            if skill is None and agent_id:
                # id lookup missed — try an exact name match within this
                # agent's skills (get() is id-first and org-scoped already).
                for s in await skill_store.list(agent_id=agent_id, org_id=org_id, limit=200):
                    if s.name == (name or "").strip():
                        skill = s
                        break
            if skill is None:
                return {"error": f"Skill '{name}' not found"}
            try:
                await skill_store.increment_usage(skill.id, org_id=org_id)
            except SQLAlchemyError:
                # Best-effort counter only; a failed bump must never fail the
                # read. DBAPI/connection failures surface as SQLAlchemyError.
                logger.debug("usage bump failed for skill %s", skill.id)
            content = skill.content or ""
            return {
                "result": content[:_MAX_CHARS]
                + ("..." if len(content) > _MAX_CHARS else ""),
                "name": skill.name,
                "description": skill.description,
                "usage_count": skill.usage_count,
            }
        except Exception as e:
            logger.exception("ReadSkillTool error for: %s", name)
            return {"error": str(e)}


TOOL_REGISTRY["read_skill"] = {
    "code_reference": "aios.tools.read_skill.ReadSkillTool",
}
