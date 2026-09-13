from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

ProviderType = Literal["baileys", "cloud", "coexistence"]

@dataclass
class OutboundMessage:
    to: str
    text: str | None = None
    media_url: str | None = None
    template: dict | None = None

@dataclass
class SendResult:
    ok: bool
    message_id: str | None = None
    error: str | None = None
    status_code: int | None = None

@dataclass
class HealthStatus:
    connected: bool
    provider: ProviderType
    risk_score: int = 0
    proxy_id: str | None = None

class WhatsAppProvider(ABC):
    provider_type: ProviderType

    @abstractmethod
    async def send(self, instance: str, msg: OutboundMessage) -> SendResult: ...

    @abstractmethod
    async def health(self, instance: str) -> HealthStatus: ...

    @abstractmethod
    async def create_instance(self, name: str) -> dict: ...

    @abstractmethod
    async def delete_instance(self, name: str) -> dict: ...
