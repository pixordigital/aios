"""Conversation handle — message, stream, history."""

from typing import Any


class ConversationHandle:
    """A conversation with an agent — send messages, get replies."""

    def __init__(self, client, data: dict):
        self._c = client
        self.id = data["id"]
        self.agent_id = data.get("agent_id")
        self.team_id = data.get("team_id")
        self.channel = data.get("channel", "web")
        self._data = data

    async def send(self, message: str) -> str:
        """Send a message and return the agent's reply."""
        result = await self._c._post(
            f"/api/conversations/{self.id}/messages",
            json={"content": message},
        )
        reply = result.get("reply")
        if reply:
            return reply.get("content", "")
        return ""

    async def messages(self, limit: int = 50) -> list[dict]:
        """Get conversation history."""
        return await self._c._get(f"/api/conversations/{self.id}/messages", params={"limit": limit})

    async def upload_file(self, filepath: str, description: str = "") -> dict:
        """Upload a file to this conversation."""
        import httpx
        files = {"file": open(filepath, "rb")}
        form = {"conversation_id": self.id, "description": description}
        headers = await self._c._headers()
        headers.pop("Content-Type", None)
        async with httpx.AsyncClient(base_url=self._c.base_url) as client:
            resp = await client.post("/api/files/upload", headers=headers, data=form, files=files)
            resp.raise_for_status()
            return resp.json()

    def __repr__(self):
        return f"<Conversation {self.id[:12]}... agent={self.agent_id[:12] if self.agent_id else None}>"
