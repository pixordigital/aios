"""LIA API: acquisition records, suppression, contact gate and CRM handoff."""

from aios.core.crm_intelligence import Contact
from aios.db.models import Organization
from aios.core.lia import Campaign, CampaignMember, SuppressionEntry


async def test_sources_and_suppression(auth_client):
    resp = await auth_client.post(
        "/api/lia/sources",
        json={"name": "CNPJ registry", "source_type": "receita_cnpj", "allowed_for_outreach": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["allowed_for_outreach"] is False

    resp = await auth_client.post("/api/lia/sources", json={"name": "x", "source_type": "magic"})
    assert resp.status_code == 400

    resp = await auth_client.post(
        "/api/lia/suppression", json={"kind": "email", "value": "opt@example.com"}
    )
    assert resp.status_code == 200, resp.text
    resp = await auth_client.post(
        "/api/lia/suppression", json={"kind": "email", "value": "opt@example.com"}
    )
    assert resp.json()["already_present"] is True
    assert len((await auth_client.get("/api/lia/suppression")).json()["items"]) == 1


async def test_contact_check_fail_closed(auth_client):
    base = {
        "channel": "email", "contact_allowed": True, "campaign_approved": True,
        "campaign_legal_reviewed": True, "email_verified": True,
    }
    resp = await auth_client.post("/api/lia/contact-check", json=base)
    assert resp.json()["allowed"] is True

    await auth_client.post(
        "/api/lia/suppression", json={"kind": "email", "value": "opt@example.com"}
    )
    resp = await auth_client.post(
        "/api/lia/contact-check", json={**base, "value": "opt@example.com"}
    )
    assert resp.json()["allowed"] is False
    assert resp.json()["suppressed"] is True

    resp = await auth_client.post(
        "/api/lia/contact-check", json={**base, "channel": "whatsapp_business"}
    )
    assert resp.json()["reason"] == "no authorised WhatsApp conversation"

    resp = await auth_client.post(
        "/api/lia/contact-check", json={**base, "channel": "carrier_pigeon"}
    )
    assert resp.json()["reason"] == "unsupported channel"

    src = await auth_client.post(
        "/api/lia/sources",
        json={"name": "Directory", "source_type": "industry_directory", "allowed_for_outreach": False},
    )
    sid = src.json()["id"]
    resp = await auth_client.post("/api/lia/contact-check", json={**base, "source_id": sid})
    assert resp.json()["allowed"] is False
    assert resp.json()["reason"] == "source not allowed for outreach"


async def test_campaign_approval_requires_legal_and_founder(
    auth_client, test_db_session, test_org, test_user
):
    resp = await auth_client.post(
        "/api/lia/campaigns", json={"name": "Dealership outbound", "channel": "email"}
    )
    assert resp.status_code == 200, resp.text
    cid = resp.json()["id"]

    resp = await auth_client.post(f"/api/lia/campaigns/{cid}/approve")
    assert resp.status_code == 400  # legal review missing

    campaign = await test_db_session.get(Campaign, cid)
    campaign.legal_reviewed = True
    await test_db_session.commit()

    resp = await auth_client.post(f"/api/lia/campaigns/{cid}/approve")
    assert resp.status_code == 403  # admin is not Founder

    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()
    resp = await auth_client.post(f"/api/lia/campaigns/{cid}/approve")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"


async def test_member_handoff_respects_suppression_and_stage_transitions(
    auth_client, test_db_session, test_org
):
    resp = await auth_client.post(
        "/api/lia/campaigns", json={"name": "Outbound", "channel": "email", "legal_reviewed": True}
    )
    cid = resp.json()["id"]
    contact = Contact(org_id=test_org.id, name="Lead", email="lead@example.com",
                      email_verified=True, contact_allowed=True)
    test_db_session.add(contact)
    await test_db_session.flush()
    resp = await auth_client.post(
        "/api/lia/members",
        json={"campaign_id": cid, "contact_id": contact.id, "disposition": "qualified", "icp_fit": 0.9},
    )
    assert resp.status_code == 200, resp.text
    mid = resp.json()["id"]

    bad_stage = await auth_client.post(f"/api/lia/members/{mid}/stage", json={"stage": "meeting_booking"})
    assert bad_stage.status_code == 400
    ok_stage = await auth_client.post(f"/api/lia/members/{mid}/stage", json={"stage": "prospect_intelligence"})
    assert ok_stage.status_code == 200
    assert ok_stage.json()["stage"] == "prospect_intelligence"

    flags = {"campaign_approved": True, "campaign_legal_reviewed": True}
    resp = await auth_client.post(f"/api/lia/members/{mid}/handoff", json=flags)
    assert resp.json()["handoff"] is True
    assert resp.json()["next_action"] == "create_or_update_deal"

    test_db_session.add(SuppressionEntry(org_id=test_org.id, kind="email", value="lead@example.com"))
    await test_db_session.commit()
    resp = await auth_client.post(f"/api/lia/members/{mid}/handoff", json=flags)
    assert resp.json()["handoff"] is False
    assert resp.json()["disposition"] == "restricted"
    assert resp.json()["next_action"] == "suppress"


async def test_lia_records_are_tenant_scoped(auth_client, test_db_session):
    other = Organization(name="Other", slug="other-lia-org")
    test_db_session.add(other)
    await test_db_session.flush()
    secret = Campaign(org_id=other.id, name="Secret campaign", channel="email")
    test_db_session.add(secret)
    await test_db_session.commit()

    resp = await auth_client.get("/api/lia/campaigns")
    assert all(c["name"] != "Secret campaign" for c in resp.json()["items"])
    resp = await auth_client.post(f"/api/lia/campaigns/{secret.id}/approve")
    assert resp.status_code == 404


async def test_lia_mutating_track_c_autonomous_guard(auth_client, test_db_session, test_org):
    # source create guarded
    resp = await auth_client.post(
        "/api/lia/sources",
        json={"name": "Auto src", "source_type": "receita_cnpj", "allowed_for_outreach": False, "track": "C", "autonomous": True},
    )
    assert resp.status_code == 403

    resp = await auth_client.post(
        "/api/lia/sources",
        json={"name": "Auto src", "source_type": "receita_cnpj", "allowed_for_outreach": False, "track": "C", "autonomous": True, "evidence": ["ok"], "founder_approved": True},
    )
    assert resp.status_code == 200, resp.text

    resp = await auth_client.post(
        "/api/lia/campaigns",
        json={"name": "C", "channel": "email", "track": "C", "autonomous": True},
    )
    assert resp.status_code == 403
    resp = await auth_client.post(
        "/api/lia/campaigns",
        json={"name": "C", "channel": "email", "track": "C", "autonomous": True, "evidence": ["ok"], "founder_approved": True},
    )
    assert resp.status_code == 200, resp.text
    cid = resp.json()["id"]

    contact = Contact(org_id=test_org.id, name="Lead", email="lead2@example.com", email_verified=True, contact_allowed=True)
    test_db_session.add(contact)
    await test_db_session.flush()
    resp = await auth_client.post(
        "/api/lia/members",
        json={"campaign_id": cid, "contact_id": contact.id, "disposition": "qualified", "icp_fit": 0.9, "track": "C", "autonomous": True},
    )
    assert resp.status_code == 403
    resp = await auth_client.post(
        "/api/lia/members",
        json={"campaign_id": cid, "contact_id": contact.id, "disposition": "qualified", "icp_fit": 0.9, "track": "C", "autonomous": True, "evidence": ["ok"], "founder_approved": True},
    )
    assert resp.status_code == 200, resp.text
    mid = resp.json()["id"]

    resp = await auth_client.post(f"/api/lia/members/{mid}/handoff", json={"campaign_approved": True, "campaign_legal_reviewed": True, "track": "C", "autonomous": True})
    assert resp.status_code == 403
    resp = await auth_client.post(f"/api/lia/members/{mid}/handoff", json={"campaign_approved": True, "campaign_legal_reviewed": True, "track": "C", "autonomous": True, "evidence": ["ok"], "founder_approved": True})
    assert resp.status_code == 200, resp.text
