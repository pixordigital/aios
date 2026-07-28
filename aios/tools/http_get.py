"""HTTP GET tool — fetch URL content for the agent."""

import logging

from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)


class HttpGetInput(BaseModel):
    url: str = Field(description="URL to fetch (https://...)")
    max_bytes: int = Field(default=50000, description="Max response body bytes")


class HttpGetTool(BaseTool):
    name = "http_get"
    description = "Fetch a URL and return its text content (max 50KB by default)"
    input_model = HttpGetInput

    async def run(self, url: str, max_bytes: int = 50000) -> dict:
        if not url.startswith("https://"):
            return {"error": "Only HTTPS URLs allowed", "content": ""}
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "AIOS/1.0"})
                resp.raise_for_status()
                content = resp.text[:max_bytes]
                return {"status": resp.status_code, "content": content, "truncated": len(resp.text) > max_bytes}
        except Exception as e:
            logger.exception("HTTP GET failed for %s", url)
            return {"error": str(e), "content": ""}


TOOL_REGISTRY["http_get"] = {
    "code_reference": "aios.tools.http_get.HttpGetTool",
}
