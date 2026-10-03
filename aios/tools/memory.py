"""Memory Tool — the agent curates its own persistent blocks.

Two targets: `memory` (this agent's notes: env facts, conventions, lessons)
and `user` (the human's profile: preferences, style). Both inject frozen at
the next run's start; writes here take effect from the following run, not
mid-conversation.

Save durable facts and corrections, not trivia or re-discoverable info.
When the block is full the tool says so and shows current entries — merge or
drop entries with replace/remove in the same turn, then retry.
"""

import logging

from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)


class MemoryInput(BaseModel):
    action: str = Field(description="add | replace | remove")
    target: str = Field(default="memory", description="memory (agent notes) | user (human profile)")
    old_text: str = Field(default="", description="Unique substring locating the entry (replace/remove)")
    content: str = Field(default="", description="Entry text (add) or full replacement text (replace)")


class MemoryTool(BaseTool):
    name = "memory"
    description = (
        "Curate persistent memory. add: store one durable fact or lesson "
        "(target memory for agent notes, user for human preferences). "
        "replace/remove: update by unique substring in old_text. "
        "Changes apply from the next run. "
        "Save: user preferences, corrections, env facts, conventions, completed work. "
        "Skip: vague remarks, re-discoverable facts, raw dumps, one-off context."
    )
    input_model = MemoryInput

    async def run(self, action: str, target: str = "memory",
                  old_text: str = "", content: str = "") -> dict:
        try:
            from aios.core import curated

            org_id = getattr(self, "_org_id", "") or ""
            agent_id = getattr(self, "_agent_id", "") or ""
            if not agent_id or not org_id:
                return {"error": "memory needs an agent and org context"}
            if target not in ("memory", "user"):
                return {"error": "target must be 'memory' or 'user'"}
            if action not in ("add", "replace", "remove"):
                return {"error": "action must be 'add', 'replace' or 'remove'"}

            blocks = await curated.load_blocks(agent_id, org_id)
            entries = blocks[target]
            if action == "add":
                new_entries, err = curated.add_entry(entries, target, content)
            elif action == "replace":
                if not old_text:
                    return {"error": "replace needs old_text locating the entry"}
                new_entries, err = curated.replace_entry(entries, target, old_text, content)
            else:
                if not old_text:
                    return {"error": "remove needs old_text locating the entry"}
                new_entries, err = curated.remove_entry(entries, old_text)
            if err:
                return err
            if not await curated.save_block(target, new_entries, agent_id, org_id):
                return {"error": "could not persist — try again"}
            used, limit = curated.usage(new_entries, target)
            return {
                "result": f"{action}d {target} entry",
                "usage": f"{used}/{limit}",
            }
        except Exception as e:
            logger.exception("MemoryTool error")
            return {"error": str(e)}


TOOL_REGISTRY["memory"] = {
    "code_reference": "aios.tools.memory.MemoryTool",
}
