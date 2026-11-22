"""LIA → CRM handoff is deterministic and inherits the LIA contact gate."""
from types import SimpleNamespace

from aios.core.lia import crm_handoff_decision


def _member(**kw):
    data = {
        "id": "m1",
        "campaign_id": "c1",
        "account_id": "a1",
        "disposition": "qualified",
        "icp_fit": 0.9,
        "recency_days": 2,
    }
    data.update(kw)
    return SimpleNamespace(**data)


def _contact(**kw):
    data = {
        "id": "p1",
        "contact_allowed": True,
        "email_verified": True,
        "opt_out_at": None,
    }
    data.update(kw)
    return SimpleNamespace(**data)


APPROVED = dict(
    campaign_approved=True,
    campaign_legal_reviewed=True,
)


def test_qualified_eligible_lead_hands_off_to_crm():
    d = crm_handoff_decision(_member(), _contact(), **APPROVED)
    assert d["handoff"] is True
    assert d["next_action"] == "create_or_update_deal"
    assert d["score"] > 0
    assert d["provenance"]["source"] == "lia"


def test_suppression_becomes_restricted_and_never_hands_off():
    d = crm_handoff_decision(_member(), _contact(), suppressed=True, **APPROVED)
    assert d["handoff"] is False
    assert d["disposition"] == "restricted"
    assert d["next_action"] == "suppress"
    assert d["score"] == 0.0


def test_unapproved_campaign_does_not_hands_off():
    d = crm_handoff_decision(_member(), _contact(), campaign_approved=False, campaign_legal_reviewed=True)
    assert d["handoff"] is False
    assert d["reason"] == "campaign not approved"


def test_research_required_stays_in_lia():
    d = crm_handoff_decision(
        _member(disposition="research_required"), _contact(), **APPROVED
    )
    assert d["handoff"] is False
    assert d["next_action"] == "enrich_account"
    assert d["score"] > 0


def test_whatsapp_requires_authorised_conversation():
    d = crm_handoff_decision(
        _member(), _contact(), channel="whatsapp_business", whatsapp_authorized=False, **APPROVED
    )
    assert d["handoff"] is False
    assert d["reason"] == "no authorised WhatsApp conversation"


def test_unknown_channel_fails_closed():
    d = crm_handoff_decision(_member(), _contact(), channel="telegram", **APPROVED)
    assert d["handoff"] is False
    assert d["reason"] == "unsupported channel"
