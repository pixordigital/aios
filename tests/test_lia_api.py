"""LIA API: acquisition records, suppression, contact gate and CRM handoff."""

from datetime import datetime, timedelta

from sqlalchemy import select

from aios.core.crm_intelligence import Contact
from aios.db.models import Organization
from aios.core.lia import Campaign, CampaignMember, LeadSource, SuppressionEntry
from aios.governance.security import SecurityEvent


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


async def test_campaign_approve_track_c_autonomous_guard(auth_client, test_db_session, test_org, test_user):
    resp = await auth_client.post(
        "/api/lia/campaigns", json={"name": "Guarded", "channel": "email", "legal_reviewed": True}
    )
    cid = resp.json()["id"]
    test_org.extra_data = {"founder_user_id": test_user.id}
    await test_db_session.commit()
    resp = await auth_client.post(f"/api/lia/campaigns/{cid}/approve", json={"track": "C", "autonomous": True})
    assert resp.status_code == 403
    resp = await auth_client.post(
        f"/api/lia/campaigns/{cid}/approve",
        json={"track": "C", "autonomous": True, "evidence": ["ok"], "founder_approved": True},
    )
    assert resp.status_code == 200, resp.text


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


async def test_lia_track_c_mode_markers_and_evidence_keys_fail_closed(auth_client, test_db_session, test_org):
    base = {
        "name": "Mode src",
        "source_type": "receita_cnpj",
        "allowed_for_outreach": False,
        "track": "C",
        "optimization_mode": "track_c_autonomous",
    }
    resp = await auth_client.post("/api/lia/sources", json=base)
    assert resp.status_code == 403
    resp = await auth_client.post(
        "/api/lia/sources",
        json={**base, "track_c_evidence": ["ev"], "founder_approved": True},
    )
    assert resp.status_code == 200, resp.text

    resp = await auth_client.post(
        "/api/lia/campaigns",
        json={
            "name": "Mode campaign",
            "channel": "email",
            "track": "C",
            "permissions": {"mode": "auto_optimize"},
        },
    )
    assert resp.status_code == 403
    resp = await auth_client.post(
        "/api/lia/campaigns",
        json={
            "name": "Mode campaign",
            "channel": "email",
            "track": "C",
            "permissions": {"mode": "auto_optimize", "evidence_refs": ["ref"], "founder_approved": True},
        },
    )
    assert resp.status_code == 200, resp.text
    cid = resp.json()["id"]

    contact = Contact(org_id=test_org.id, name="Lead3", email="lead3@example.com", email_verified=True, contact_allowed=True)
    test_db_session.add(contact)
    await test_db_session.flush()
    member_payload = {
        "campaign_id": cid,
        "contact_id": contact.id,
        "disposition": "qualified",
        "icp_fit": 0.9,
        "track": "C",
        "permissions": {"optimization_mode": "autonomous"},
    }
    resp = await auth_client.post("/api/lia/members", json=member_payload)
    assert resp.status_code == 403
    resp = await auth_client.post(
        "/api/lia/members",
        json={**member_payload, "track_c_evidence": ["ev2"], "founder_approved": True},
    )
    assert resp.status_code == 200, resp.text
    mid = resp.json()["id"]

    resp = await auth_client.post(
        f"/api/lia/members/{mid}/handoff",
        json={"campaign_approved": True, "campaign_legal_reviewed": True, "track": "C", "mode": "track_c_autonomous"},
    )
    assert resp.status_code == 403
    resp = await auth_client.post(
        f"/api/lia/members/{mid}/handoff",
        json={
            "campaign_approved": True,
            "campaign_legal_reviewed": True,
            "track": "C",
            "mode": "track_c_autonomous",
            "permissions": {"track_c_evidence": ["ev3"]},
            "founder_approved": True,
        },
    )
    assert resp.status_code == 200, resp.text


def _lia_cross_tenant_metrics(rows, *, resource_type, resource_org_id, source):
    return [
        e
        for e in rows
        if e.event_type == "security.cross_tenant.blocked"
        and e.payload.get("metric") == "cross_tenant_block"
        and e.payload.get("resource_type") == resource_type
        and str(e.payload.get("resource_org_id")) == str(resource_org_id)
        and e.source == source
    ]


async def test_lia_cross_tenant_campaign_approve_records_metric(auth_client, test_db_session, second_org):
    campaign = Campaign(org_id=second_org.id, name="Secret", channel="email", legal_reviewed=True)
    test_db_session.add(campaign)
    await test_db_session.commit()
    await test_db_session.refresh(campaign)

    resp = await auth_client.post(f"/api/lia/campaigns/{campaign.id}/approve")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "campaign not found"

    rows = (await test_db_session.execute(select(SecurityEvent))).scalars().all()
    assert _lia_cross_tenant_metrics(
        rows, resource_type="Campaign", resource_org_id=second_org.id, source="lia.api.approve_campaign"
    )


async def test_lia_cross_tenant_member_lookups_record_metric(auth_client, test_db_session, test_org, second_org):
    foreign_campaign = Campaign(org_id=second_org.id, name="Foreign", channel="email")
    foreign_member_campaign = Campaign(org_id=second_org.id, name="Foreign2", channel="email")
    test_db_session.add_all([foreign_campaign, foreign_member_campaign])
    await test_db_session.flush()
    foreign_member = CampaignMember(org_id=second_org.id, campaign_id=foreign_member_campaign.id, stage="company_discovery")
    test_db_session.add(foreign_member)
    await test_db_session.commit()
    await test_db_session.refresh(foreign_campaign)
    await test_db_session.refresh(foreign_member)

    resp = await auth_client.post("/api/lia/members", json={"campaign_id": foreign_campaign.id})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "campaign not found"

    resp = await auth_client.post(f"/api/lia/members/{foreign_member.id}/stage", json={"stage": "prospect_intelligence"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "member not found"

    resp = await auth_client.post(f"/api/lia/members/{foreign_member.id}/handoff", json={"campaign_approved": True, "campaign_legal_reviewed": True})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "member not found"

    rows = (await test_db_session.execute(select(SecurityEvent))).scalars().all()
    assert _lia_cross_tenant_metrics(
        rows, resource_type="Campaign", resource_org_id=second_org.id, source="lia.api.create_member.campaign"
    )
    assert _lia_cross_tenant_metrics(
        rows, resource_type="CampaignMember", resource_org_id=second_org.id, source="lia.api.advance_stage.member"
    )
    assert _lia_cross_tenant_metrics(
        rows, resource_type="CampaignMember", resource_org_id=second_org.id, source="lia.api.handoff.member"
    )


async def test_lia_cross_tenant_source_lookups_record_metric(auth_client, test_db_session, test_org, second_org):
    foreign_source = LeadSource(org_id=second_org.id, name="Foreign src", source_type="receita_cnpj", allowed_for_outreach=True)
    test_db_session.add(foreign_source)
    await test_db_session.flush()
    local_campaign = Campaign(org_id=test_org.id, name="Local", channel="email")
    test_db_session.add(local_campaign)
    await test_db_session.flush()
    local_contact = Contact(org_id=test_org.id, name="Lead", email="l@example.com", email_verified=True, contact_allowed=True)
    test_db_session.add(local_contact)
    await test_db_session.flush()
    local_member = CampaignMember(org_id=test_org.id, campaign_id=local_campaign.id, contact_id=local_contact.id, stage="company_discovery", disposition="qualified")
    test_db_session.add(local_member)
    await test_db_session.commit()
    await test_db_session.refresh(foreign_source)
    await test_db_session.refresh(local_member)

    resp = await auth_client.post(
        "/api/lia/contact-check",
        json={
            "channel": "email",
            "contact_allowed": True,
            "campaign_approved": True,
            "campaign_legal_reviewed": True,
            "email_verified": True,
            "source_id": foreign_source.id,
        },
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "source not found"

    resp = await auth_client.post(
        f"/api/lia/members/{local_member.id}/handoff",
        json={"campaign_approved": True, "campaign_legal_reviewed": True, "source_id": foreign_source.id},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "source not found"

    rows = (await test_db_session.execute(select(SecurityEvent))).scalars().all()
    assert _lia_cross_tenant_metrics(
        rows, resource_type="LeadSource", resource_org_id=second_org.id, source="lia.api.contact_check.source"
    )
    assert _lia_cross_tenant_metrics(
        rows, resource_type="LeadSource", resource_org_id=second_org.id, source="lia.api.handoff.source"
    )


async def test_suppression_list_bounded_page_and_offset(
    auth_client, test_db_session, test_org, second_org
):
    base_created = datetime(2026, 1, 1)
    own = [
        SuppressionEntry(
            org_id=test_org.id, kind="email", value=f"own{i}@example.com", reason="opt_out",
            created_at=base_created + timedelta(minutes=i),
        )
        for i in range(3)
    ]
    foreign = SuppressionEntry(
        org_id=second_org.id, kind="email", value="foreign@example.com", reason="opt_out"
    )
    test_db_session.add_all([*own, foreign])
    await test_db_session.commit()

    all_resp = await auth_client.get("/api/lia/suppression")
    assert all_resp.status_code == 200, all_resp.text
    all_body = all_resp.json()
    assert all_body["truncated"] is False
    assert "total" not in all_body
    assert {e["value"] for e in all_body["items"]} == {e.value for e in own}
    assert set(all_body["items"][0]) == {"id", "kind", "value", "reason"}

    first = await auth_client.get("/api/lia/suppression", params={"limit": 2})
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["items"]) == 2
    assert body["truncated"] is True
    assert "total" not in body

    second = await auth_client.get("/api/lia/suppression", params={"limit": 2, "offset": 2})
    assert second.status_code == 200, second.text
    body = second.json()
    assert len(body["items"]) == 1
    assert body["truncated"] is False

    expected_order = [
        e.id for e in sorted(own, key=lambda e: (e.created_at, e.id), reverse=True)
    ]
    assert [e["id"] for e in all_body["items"]] == expected_order
    assert [e["id"] for e in first.json()["items"]] == expected_order[:2]
    assert [e["id"] for e in second.json()["items"]] == expected_order[2:]

    own_ids = {e["id"] for e in all_body["items"]}
    first_ids = {e["id"] for e in first.json()["items"]}
    second_ids = {e["id"] for e in second.json()["items"]}
    assert first_ids | second_ids == own_ids
    assert first_ids.isdisjoint(second_ids)

    first_repeat = await auth_client.get("/api/lia/suppression", params={"limit": 2})
    assert [e["id"] for e in first_repeat.json()["items"]] == expected_order[:2]
    second_repeat = await auth_client.get(
        "/api/lia/suppression", params={"limit": 2, "offset": 2}
    )
    assert [e["id"] for e in second_repeat.json()["items"]] == expected_order[2:]

    for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}):
        bad = await auth_client.get("/api/lia/suppression", params=params)
        assert bad.status_code == 422, bad.text
