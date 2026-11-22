"""Slack taxonomy is a proposal; no structural change without an approved map."""

import pytest

from aios.governance.slack_taxonomy import (
    PROPOSED_CHANNELS,
    SYSTEM_OF_RECORD,
    TaxonomyError,
    migration_steps,
    slack_may_become_decision,
    validate_channel,
)


def test_known_channels_validate():
    assert validate_channel("departments", "dept-sales") == "dept-sales"
    assert validate_channel("restricted_governance", "security-incidents")


def test_unknown_channel_rejected():
    with pytest.raises(TaxonomyError):
        validate_channel("departments", "general")
    with pytest.raises(TaxonomyError):
        validate_channel("nope", "dept-sales")


def test_no_agent_channels():
    with pytest.raises(TaxonomyError):
        validate_channel("departments", "agent-foo")


def test_slack_never_becomes_the_decision_record():
    assert slack_may_become_decision() is False
    assert SYSTEM_OF_RECORD["approvals"] == "aios_decision_approval"
    assert SYSTEM_OF_RECORD["tasks"] == "aios_ocp"


def test_restricted_areas_present_and_migration_gated():
    assert "restricted_governance" in PROPOSED_CHANNELS
    steps = migration_steps()
    assert any("founder approval" in s for s in steps)
    assert steps[0].startswith("inspect")
