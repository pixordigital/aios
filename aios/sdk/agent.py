"""Agent handle — deploy, message, manage."""

from typing import Any


class AgentHandle:
    """A deployed agent that can process messages."""

    def __init__(self, client, data: dict):
        self._c = client
        self.id = data["id"]
        self.name = data.get("name", "")
        self.agent_type = data.get("agent_type", "")
        self.status = data.get("status", "draft")
        self._data = data

    async def deploy(self):
        """Activate this agent."""
        result = await self._c._post(f"/api/agents/{self.id}/deploy")
        self.status = "active"
        return result

    async def stop(self):
        """Deactivate this agent."""
        result = await self._c._post(f"/api/agents/{self.id}/stop")
        self.status = "draft"
        return result

    async def update(self, **kwargs) -> dict:
        """Update agent config."""
        data = await self._c._put(f"/api/agents/{self.id}", json=kwargs)
        self._data = data
        return data

    async def send(self, message: str) -> str:
        """Quick message — creates a conversation, sends, returns reply."""
        conv = await self._c.conversations.create(self.id, channel="api")
        reply = await conv.send(message)
        return reply

    def __repr__(self):
        return f"<Agent {self.name} ({self.agent_type}) [{self.status}]>"
