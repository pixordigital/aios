"""LIA contact gate: no channel bypasses suppression, approval or LGPD review."""

from aios.core.lia import (
    can_contact,
    channel_priority,
    human_approval_required,
    stop_sequence,
)

GOOD = dict(
    contact_allowed=True,
    opt_out=False,
    suppressed=False,
    campaign_approved=True,
    campaign_legal_reviewed=True,
    email_verified=True,
)


def test_email_requires_review_and_approval():
    assert can_contact(channel="email", **GOOD)[0]
    bad = dict(GOOD, campaign_legal_reviewed=False)
    assert not can_contact(channel="email", **bad)[0]


def test_suppression_and_opt_out_always_block():
    assert not can_contact(channel="email", **dict(GOOD, suppressed=True))[0]
    assert not can_contact(channel="email", **dict(GOOD, opt_out=True))[0]


def test_whatsapp_needs_authorised_conversation():
    assert not can_contact(channel="whatsapp_business", **GOOD)[0]
    assert can_contact(channel="whatsapp_business", whatsapp_authorized=True, **GOOD)[0]


def test_unverified_email_is_not_labelled_verified():
    assert not can_contact(channel="email", **dict(GOOD, email_verified=False))[0]


def test_unknown_channel_fails_closed():
    assert not can_contact(channel="telegram", **GOOD)[0]


def test_approval_and_sequence_rules():
    assert human_approval_required("pricing")
    assert human_approval_required("contract")
    assert not human_approval_required("introduction")
    assert stop_sequence("opt_out")
    assert stop_sequence("reply")
    assert not stop_sequence("no_reply")


def test_channel_priority_p0_first():
    assert channel_priority("email") == 0
    assert channel_priority("whatsapp_business") == 1
    assert channel_priority("linkedin_human") == 2
    assert channel_priority("sms") == 99
