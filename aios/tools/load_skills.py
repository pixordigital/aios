"""Load Project Skills Tool — agent can discover and load skills from project files at runtime.

Paperclip-style runtime skill injection: agents learn workflows from AGENTS.md/CLAUDE.md
without retraining. Returns formatted skill context for immediate use.
"""

import logging

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)


class LoadProjectSkillsTool(BaseTool):
    name = "load_project_skills"
    description = "Load skills from project workspace (AGENTS.md, CLAUDE.md, skills/*.md) for current task. Returns formatted context to inject into agent prompt."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Task or query to find relevant skills for"},
            "project_path": {"type": "string", "description": "Optional project path (defaults to agent's configured project_path)"},
            "max_skills": {"type": "integer", "description": "Maximum number of skills to return", "default": 5},
        },
        "required": ["query"],
    }

    async def run(self, query: str, project_path: str = "", max_skills: int = 5) -> dict:
        try:
            from aios.core.skill_loader import skill_loader

            skills = skill_loader.get_skills_for_task(query, project_path or None, max_skills=max_skills)
            if not skills:
                return {"result": "No relevant skills found for this task.", "skills": []}

            formatted = skill_loader.format_skills_for_context(skills)
            return {
                "result": formatted,
                "skills": [{"name": s.name, "source": s.source_file, "description": s.description, "tags": s.tags} for s in skills],
            }
        except Exception as e:
            logger.exception("LoadProjectSkillsTool error for query: %s", query)
            return {"error": str(e)}


TOOL_REGISTRY["load_project_skills"] = {
    "code_reference": "aios.tools.load_skills.LoadProjectSkillsTool",
}