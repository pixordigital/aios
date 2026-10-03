"""HTTP GET tool — fetch URL content for the agent."""

import logging
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from aios.tools.base import BaseTool
from aios.tools.ssrf import is_private_host as _is_private
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
        parsed = urlparse(url)
        if parsed.scheme not in ("https",):
            return {"error": "Only HTTPS URLs allowed", "content": ""}
        host = parsed.hostname or ""
        if _is_private(host):
            return {"error": "Cannot fetch private/internal URLs", "content": ""}
        try:
            import httpx
            # ponytail: no auto-follow — validate every hop's host ourselves (SSRF)
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                url_to_fetch: str = url
                for _hop in range(5):
                    resp = await client.get(url_to_fetch, headers={"User-Agent": "AIOS/1.0"})
                    if resp.status_code in (301, 302, 303, 307, 308):
                        nxt = resp.headers.get("location")
                        if not nxt:
                            break
                        url_to_fetch = str(httpx.URL(nxt).join(httpx.URL(url_to_fetch)))
                        parsed = urlparse(url_to_fetch)
                        if parsed.scheme not in ("https",) or _is_private(parsed.hostname or ""):
                            return {"error": "Redirect target is not HTTPS or is private", "content": ""}
                        continue
                    resp.raise_for_status()
                    content = resp.text[:max_bytes]
                    return {"status": resp.status_code, "content": content, "truncated": len(resp.text) > max_bytes}
                return {"error": "Too many redirects", "content": ""}
        except Exception as e:
            logger.exception("HTTP GET failed for %s", url)
            return {"error": str(e), "content": ""}


TOOL_REGISTRY["http_get"] = {
    "code_reference": "aios.tools.http_get.HttpGetTool",
}
