"""Read uploaded artifacts tool."""

import logging

from pydantic import BaseModel, Field

from aios.core.storage import get_artifact_content
from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)


class ReadFileInput(BaseModel):
    artifact_id: str = Field(description="ID of the uploaded file to read")
    max_chars: int = Field(default=10000, description="Maximum characters to read")


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read the content of an uploaded file or artifact by its ID"
    input_model = ReadFileInput

    async def run(self, artifact_id: str, max_chars: int = 10000) -> dict:
        # The engine injects `_org_id`/`_agent_id`, never a session, so this
        # waited on `self._db`, which nothing ever set: every call returned
        # "File reading requires a database session". Open a session here.
        from aios.db.backend import db_session

        org_id = getattr(self, "_org_id", "") or None
        async with db_session() as db:
            # Org set by ToolEngine. Without it any artifact UUID is readable
            # across orgs; with it, foreign rows return "not found" (no oracle).
            content = await get_artifact_content(artifact_id, db, org_id=org_id)
        if content is None:
            return {"error": "File not found", "content": ""}
        try:
            text = content.decode("utf-8")[:max_chars]
            return {"content": text, "truncated": len(content) > max_chars}
        except UnicodeDecodeError:
            return {"error": "Binary file", "content": "", "size_bytes": len(content)}


TOOL_REGISTRY["read_file"] = {
    "code_reference": "aios.tools.read_file.ReadFileTool",
}
