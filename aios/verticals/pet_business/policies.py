"""Consent, cadence and escalation rules for the pet business vertical.

Pure decisions, no I/O: the caller supplies the facts from the DB, so the same
rules are testable and cannot accidentally query the wrong tenant.
"""

from __future__ import annotations

from dataclasses import dataclass

from .profile import PetBusinessProfile


@dataclass(frozen=True)
class FollowUpDecision:
    allowed: bool
    reason: str


def _contains_opt_out(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in phrases)


def may_follow_up(
    profile: PetBusinessProfile,
    *,
    customer_text: str = "",
    opted_out: bool = False,
    follow_ups_sent: int = 0,
    hours_since_last_contact: float = 0.0,
) -> FollowUpDecision:
    """Whether one more follow-up may be sent right now, with the reason.

    Order matters: consent outranks cadence, cadence outranks the cap. A denied
    follow-up is recorded, never silently skipped.
    """
    if opted_out or _contains_opt_out(customer_text, profile.opt_out_phrases):
        return FollowUpDecision(False, "customer opted out")
    if hours_since_last_contact < profile.min_hours_between_follow_ups:
        return FollowUpDecision(
            False,
            f"minimum interval not reached "
            f"({hours_since_last_contact:.1f}h < {profile.min_hours_between_follow_ups:.1f}h)",
        )
    if follow_ups_sent >= profile.max_follow_ups:
        return FollowUpDecision(
            False, f"follow-up cap reached ({follow_ups_sent}/{profile.max_follow_ups})"
        )
    return FollowUpDecision(True, "allowed")


def requires_human(
    profile: PetBusinessProfile, text: str
) -> tuple[bool, str | None]:
    """Return ``(True, destination)`` when the message matches an escalation rule."""
    lowered = (text or "").lower()
    for keyword, destination in profile.escalation_rules.items():
        if keyword and keyword in lowered:
            return True, destination
    return False, None
