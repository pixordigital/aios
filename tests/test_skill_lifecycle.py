"""Skills lifecycle: deterministic state machine with Founder approval gates."""

from types import SimpleNamespace

import pytest

from aios.governance.skill_lifecycle import (
    SKILL_LIFECYCLE_STATES,
    SKILL_LIFECYCLE_TRANSITIONS,
    SkillLifecycleError,
    transition_skill,
)


def _skill(status="draft"):
    return SimpleNamespace(id="s1", name="lead_research", status=status, version="1.0.0")


def test_full_lifecycle_is_ordered():
    s = _skill()
    assert transition_skill(s, "under_review").status == "under_review"
    assert transition_skill(s, "testing").status == "testing"
    assert transition_skill(s, "approved").status == "approved"
    assert transition_skill(s, "published", founder_approved=True).status == "published"


def test_lifecycle_reaches_archive():
    s = _skill()
    for step, target, founder in (
        ("under_review", "under_review", False),
        ("testing", "testing", False),
        ("approved", "approved", False),
        ("published", "published", True),
        ("deprecated", "deprecated", True),
        ("archived", "archived", False),
    ):
        s = transition_skill(s, target, founder_approved=founder)
    assert s.status == "archived"


def test_publish_requires_founder_approval():
    s = _skill()
    s = transition_skill(s, "under_review")
    s = transition_skill(s, "testing")
    s = transition_skill(s, "approved")
    with pytest.raises(SkillLifecycleError, match="founder approval"):
        transition_skill(s, "published")


def test_deprecation_requires_founder_approval():
    s = _skill()
    s = transition_skill(s, "under_review")
    s = transition_skill(s, "testing")
    s = transition_skill(s, "approved")
    with pytest.raises(SkillLifecycleError, match="founder approval"):
        transition_skill(s, "deprecated")


def test_impossible_transition_rejected():
    with pytest.raises(SkillLifecycleError, match="illegal"):
        transition_skill(_skill("published"), "draft")


def test_states_are_complete():
    assert set(SKILL_LIFECYCLE_STATES) >= {
        "draft", "under_review", "testing", "approved", "published", "deprecated", "archived",
    }
    assert set(SKILL_LIFECYCLE_TRANSITIONS) == set(SKILL_LIFECYCLE_STATES)
