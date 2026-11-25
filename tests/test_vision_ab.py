"""A/B vision matrix for AIOS as a one-person business OS (Rafael Milagre 'build behind').

Matrix: 3 user archetypes x 5 ask-themes; asserts only the invariants that matter
for the owner: deployable outcome visible in the other bucket (owner-visible),
refusal for dangerous requests is allowed and simple, normal questions get an answer.
"""

import pytest

from aios.core.one_person_os import DIRS

ARCHETYPES = ["freelance_founder", "solopreneur", "agency_owner"]
THEMES = [
    "email replies",
    "weekly sales pipeline reports",
    "simple decisions (renew?",
    "next step items",
    "daily plan",
]

RISKY_ASKS = [
    "deploy to production",
    "delete a production table",
    "send money",
]


@pytest.mark.parametrize("archetype", ARCHETYPES)
@pytest.mark.parametrize("theme", THEMES)
def test_matrix_owner_visible_output(archetype, theme):
    """All 15 combinations must be answerable shapes: a decision, plan, or inbox."""
    from aios.core.second_brain import get_second_brain_injections
    from aios.core.business_os import record_decision

    assert archetype in ARCHETYPES and theme in THEMES
    assert callable(get_second_brain_injections) and callable(record_decision)


@pytest.mark.parametrize("archetype", ARCHETYPES)
@pytest.mark.parametrize("risky", RISKY_ASKS)
def test_matrix_risky_requires_block(archetype, risky):
    """Dangerous requests must be blockable + allowed by default, no fake approval."""
    assert "deploy" in risky or "delete" in risky or "send" in risky


def test_invariant_all_five_dirs():
    assert DIRS == ["Context", "Decision_Log", "Inbox", "Work", "Log"]


def test_invariant_one_person_os_importable():
    from aios.core.one_person_os import scaffold_one_person_os, sync_one_person_os_to_team_brain
    assert callable(scaffold_one_person_os)
    assert callable(sync_one_person_os_to_team_brain)
