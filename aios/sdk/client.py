"""HTTP client for AIOS API."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class AIOSClient:
    """Client for the AIOS Agent API.

    Args:
        base_url: URL of the AIOS server (e.g. http://localhost:8777)
        api_key: JWT token or API key for authentication
        org_id: Organization ID for scoping requests
    """

    def __init__(self, base_url: str, api_key: str = "", org_id: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.org_id = org_id
        self._http = httpx.AsyncClient(timeout=120, base_url=self.base_url)

    @property
    def agents(self) -> "AgentsAPI":
        return AgentsAPI(self)

    @property
    def conversations(self) -> "ConversationsAPI":
        return ConversationsAPI(self)

    @property
    def teams(self) -> "TeamsAPI":
        return TeamsAPI(self)

    async def close(self):
        await self._http.aclose()

    async def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        if self.org_id:
            h["X-Org-ID"] = self.org_id
        return h

    async def _req(self, method: str, path: str, **kw) -> Any:
        headers = await self._headers()
        resp = await self._http.request(method, path, headers=headers, **kw)
        if resp.status_code == 401:
            raise PermissionError("Invalid API key or token")
        if resp.status_code == 403:
            raise PermissionError("Access denied")
        if resp.status_code == 429:
            raise RuntimeError("Rate limited")
        resp.raise_for_status()
        if resp.status_code == 204:
            return None
        return resp.json()

    async def _get(self, path: str, **kw) -> Any:
        return await self._req("GET", path, **kw)

    async def _post(self, path: str, **kw) -> Any:
        return await self._req("POST", path, **kw)

    async def _put(self, path: str, **kw) -> Any:
        return await self._req("PUT", path, **kw)

    async def _delete(self, path: str, **kw) -> Any:
        return await self._req("DELETE", path, **kw)


# ─── Resource APIs ───


class AgentsAPI:
    def __init__(self, client: AIOSClient):
        self._c = client

    async def create(self, name: str, agent_type: str = "custom", **kwargs) -> "AgentHandle":
        """Create and deploy a new agent."""
        from .agent import AgentHandle
        data = await self._c._post("/api/agents", json={"name": name, "agent_type": agent_type, **kwargs})
        return AgentHandle(self._c, data)

    async def list(self) -> list[dict]:
        return await self._c._get("/api/agents")

    async def get(self, agent_id: str) -> "AgentHandle":
        from .agent import AgentHandle
        data = await self._c._get(f"/api/agents/{agent_id}")
        return AgentHandle(self._c, data)

    async def deploy(self, agent_id: str) -> dict:
        return await self._c._post(f"/api/agents/{agent_id}/deploy")

    async def delete(self, agent_id: str):
        await self._c._delete(f"/api/agents/{agent_id}")


class ConversationsAPI:
    def __init__(self, client: AIOSClient):
        self._c = client

    async def create(self, agent_id: str, channel: str = "web", **kwargs) -> "ConversationHandle":
        from .conversation import ConversationHandle
        data = await self._c._post("/api/conversations", json={
            "agent_id": agent_id, "channel": channel, **kwargs,
        })
        return ConversationHandle(self._c, data)

    async def list(self, **filters) -> list[dict]:
        return await self._c._get("/api/conversations", params=filters)

    async def get(self, conv_id: str) -> "ConversationHandle":
        from .conversation import ConversationHandle
        data = await self._c._get(f"/api/conversations/{conv_id}")
        return ConversationHandle(self._c, data)


class TeamsAPI:
    def __init__(self, client: AIOSClient):
        self._c = client

    async def create(self, name: str, **kwargs) -> dict:
        return await self._c._post("/api/teams", json={"name": name, **kwargs})

    async def list(self) -> list[dict]:
        return await self._c._get("/api/teams")

    async def assign_agents(self, team_id: str, agent_ids: list[str]) -> dict:
        return await self._c._post(f"/api/teams/{team_id}/agents", json={"agent_ids": agent_ids})
