"""Skills lifecycle: Draft → Under review → Testing → Approved → Published → Deprecated → Archived.

State transitions are deterministic. Publishing and deprecation require Founder
approval under the stated authority model; skills never grant permissions.
"""

from __future__ import annotations

from types import SimpleNamespace

SKILL_LIFECYCLE_STATES = (
    "draft",
    "under_review",
    "testing",
    "approved",
    "published",
    "deprecated",
    "archived",
)

# Allowed source -> target transitions.
SKILL_LIFECYCLE_TRANSITIONS = {
    "draft": ("under_review", "archived"),
    "under_review": ("testing",),
    "testing": ("approved", "draft"),
    "approved": ("published", "deprecated"),
    "published": ("deprecated", "archived"),
    "deprecated": ("archived",),
    "archived": (),
}

FOUNDER_REQUIRED = {
    ("approved", "published"),
    ("published", "deprecated"),
    ("approved", "deprecated"),
}


class SkillLifecycleError(ValueError):
    """Illegal or unaudited skill transition."""


def transition_skill(
    skill: SimpleNamespace,
    target: str,
    *,
    founder_approved: bool = False,
    actor: str = "",
) -> SimpleNamespace:
    source = skill.status or "draft"
    if target not in SKILL_LIFECYCLE_STATES:
        raise SkillLifecycleError(f"unknown skill status: {target}")
    if target not in SKILL_LIFECYCLE_TRANSITIONS.get(source, ()):
        raise SkillLifecycleError(f"illegal skill transition {source} -> {target}")
    if (source, target) in FOUNDER_REQUIRED and not founder_approved:
        raise SkillLifecycleError(f"founder approval required for {source} -> {target}")
    skill.status = target
    return skill
