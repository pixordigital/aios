"""Business profile for one pet-business customer.

Stored as configuration (currently the agent/org ``extra_data``), never
hardcoded in the runtime. The profile is what the answer layer is allowed to
quote: if a price, service or hours entry is not here, the agent must escalate
instead of inventing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

REQUIRED_FIELDS = (
    "business_name",
    "services",
    "hours",
    "escalation_rules",
)

DEFAULT_OPT_OUT_PHRASES = (
    "pare",
    "parar",
    "não quero",
    "nao quero",
    "descadastrar",
    "sair",
)


@dataclass(frozen=True)
class ServiceItem:
    """One sellable service. ``price_brl`` is ``None`` when the business has not
    approved a public price — the agent must then say it will confirm."""

    name: str
    price_brl: float | None = None
    duration_minutes: int | None = None
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServiceItem":
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("service requires a name")
        price = data.get("price_brl")
        return cls(
            name=name,
            price_brl=float(price) if price is not None else None,
            duration_minutes=(
                int(data["duration_minutes"]) if data.get("duration_minutes") else None
            ),
            notes=str(data.get("notes", "")).strip(),
        )


@dataclass(frozen=True)
class PetBusinessProfile:
    business_name: str
    services: tuple[ServiceItem, ...]
    # e.g. {"mon": "09:00-18:00", "sun": "closed"}
    hours: dict[str, str]
    # Keyword -> human destination. First match wins.
    escalation_rules: dict[str, str] = field(default_factory=dict)
    # Phrases that mean "stop messaging me". Honoured before any follow-up.
    opt_out_phrases: tuple[str, ...] = DEFAULT_OPT_OUT_PHRASES
    # Follow-ups are capped to avoid turning a lead into spam.
    max_follow_ups: int = 2
    min_hours_between_follow_ups: float = 24.0
    # Attribution is only claimed when the CRM row can be linked back to a
    # conversation; confidence is reported, never assumed.
    attribution_source: str = "crm_deal.agent_id"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PetBusinessProfile":
        missing = [f for f in REQUIRED_FIELDS if not data.get(f)]
        if missing:
            raise ValueError(f"pet business profile missing: {', '.join(missing)}")
        services = tuple(ServiceItem.from_dict(s) for s in data["services"])
        if not services:
            raise ValueError("pet business profile requires at least one service")
        return cls(
            business_name=str(data["business_name"]).strip(),
            services=services,
            hours={str(k): str(v) for k, v in dict(data["hours"]).items()},
            escalation_rules={
                str(k).lower(): str(v)
                for k, v in dict(data.get("escalation_rules") or {}).items()
            },
            opt_out_phrases=tuple(data.get("opt_out_phrases") or DEFAULT_OPT_OUT_PHRASES),
            max_follow_ups=int(data.get("max_follow_ups", 2)),
            min_hours_between_follow_ups=float(
                data.get("min_hours_between_follow_ups", 24.0)
            ),
            attribution_source=str(
                data.get("attribution_source", "crm_deal.agent_id")
            ),
        )

    def validate(self) -> list[str]:
        """Return human-readable problems; empty means onboarding is complete."""
        issues: list[str] = []
        if not self.business_name:
            issues.append("business_name is empty")
        if not self.services:
            issues.append("no services configured")
        if not self.hours:
            issues.append("no opening hours configured")
        if not self.escalation_rules:
            issues.append("no escalation rules configured")
        if self.max_follow_ups < 0:
            issues.append("max_follow_ups cannot be negative")
        if not self.opt_out_phrases:
            issues.append("opt-out phrases are empty — follow-ups cannot be stopped")
        return issues

    def service_names(self) -> Iterable[str]:
        return (s.name for s in self.services)
