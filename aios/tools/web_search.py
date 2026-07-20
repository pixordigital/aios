"""Web search tool — DuckDuckGo (free, no API key)."""

import asyncio
import logging

from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)


class WebSearchInput(BaseModel):
    query: str = Field(description="Search query")


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web for current information"
    input_model = WebSearchInput

    async def run(self, query: str) -> dict:
        try:
            from duckduckgo_search import DDGS
            results = []
            # run sync duckduckgo in thread to avoid blocking event loop
            def _search():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=5))

            for r in await asyncio.to_thread(_search):
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", ""),
                })
            return {"results": results}
        except ImportError:
            logger.warning("duckduckgo_search not installed, falling back to placeholder")
            return {"results": [{"title": "Search unavailable", "snippet": "Install duckduckgo_search package", "url": ""}]}
        except Exception as e:
            logger.error("Web search failed: %s", e)
            return {"results": [{"title": "Search error", "snippet": str(e), "url": ""}]}


TOOL_REGISTRY["web_search"] = {
    "code_reference": "aios.tools.web_search.WebSearchTool",
}
