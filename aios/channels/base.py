"""Channel abstraction — all adapters implement this."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class OutboundMessage:
    conversation_id: str
    text: str
    channel_connection_id: str
    extra_data: dict | None = None


@dataclass
class InboundMessage:
    text: str
    conversation_id: str
    channel_connection_id: str
    user_id: str = ""
    extra_data: dict | None = None


class Channel(ABC):
    channel_type: str = ""

    @abstractmethod
    async def send(self, message: OutboundMessage) -> str | None:
        ...

    @abstractmethod
    async def start(self) -> None:
        ...

    @abstractmethod
    async def stop(self) -> None:
        ...

    async def test(self) -> dict:
        """Test connection. Returns {"ok": True/False, "message": "..."}."""
        return {"ok": False, "message": f"No test implemented for {self.channel_type}"}
