"""Business profile for one US car dealership.

Stored as configuration (e.g. org/agent extra_data), never hardcoded in the
runtime. The answer layer may only quote facts present here; if price,
availability, hours, or policy is not listed, the agent must escalate.
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

# Common opt-out phrases (EN + common ES) to stop follow-ups.
DEFAULT_OPT_OUT_PHRASES = (
    "stop",
    "unsubscribe",
    "do not contact",
    "don't contact",
    "remove me",
    "opt out",
    "no more messages",
    "pare",
    "parar",
    "no quiero",
    "baja",
)


@dataclass(frozen=True)
class ServiceItem:
    """One sellable/service offering. ``price_usd`` None means not publicly
    approved — agent must say it will confirm."""

    name: str
    price_usd: float | None = None
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServiceItem":
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("service requires a name")
        price = data.get("price_usd")
        if price is None:
            price = data.get("price")  # allow generic key
        return cls(
            name=name,
            price_usd=float(price) if price is not None else None,
            notes=str(data.get("notes", "")).strip(),
        )


@dataclass(frozen=True)
class CarDealershipUSProfile:
    business_name: str
    services: tuple[ServiceItem, ...]
    # e.g. {"mon": "09:00-19:00", "sun": "closed"}
    hours: dict[str, str]
    # Keyword (lowercased match) -> human destination/team.
    escalation_rules: dict[str, str] = field(default_factory=dict)
    opt_out_phrases: tuple[str, ...] = DEFAULT_OPT_OUT_PHRASES
    max_follow_ups: int = 2
    min_hours_between_follow_ups: float = 24.0
    attribution_source: str = "crm_deal.agent_id"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CarDealershipUSProfile":
        missing = [f for f in REQUIRED_FIELDS if not data.get(f)]
        if missing:
            raise ValueError(f"car dealership (US) profile missing: {', '.join(missing)}")
        services = tuple(ServiceItem.from_dict(s) for s in data["services"])
        if not services:
            raise ValueError("car dealership (US) profile requires at least one service/offering")
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
        issues: list[str] = []
        if not self.business_name:
            issues.append("business_name is empty")
        if not self.services:
            issues.append("no services/offerings configured")
        if not self.hours:
            issues.append("no hours configured")
        if not self.escalation_rules:
            issues.append("no escalation rules configured")
        if self.max_follow_ups < 0:
            issues.append("max_follow_ups cannot be negative")
        if not self.opt_out_phrases:
            issues.append("opt-out phrases empty — follow-ups cannot be stopped")
        return issues

    def service_names(self) -> Iterable[str]:
        return (s.name for s in self.services)
