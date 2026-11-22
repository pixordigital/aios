"""CRM accounts/contacts, health and prioritisation."""

from datetime import datetime

from aios.core.crm_intelligence import (
    Account,
    Contact,
    InteractionEvent,
    deal_360_payload,
    deal_entity_kind,
    relationship_health,
    retention_cutoff,
    sales_priority,
)
from aios.db.backend import db_session
from aios.db.models import CrmDeal, Organization


def test_health_penalises_stale_and_overdue():
    good, _ = relationship_health(
        days_since_last_contact=3, open_commitments=0, overdue_commitments=0, support_tickets_open=0
    )
    bad, reason = relationship_health(
        days_since_last_contact=90, open_commitments=2, overdue_commitments=2, support_tickets_open=4
    )
    assert good > bad
    assert "stale" in reason


def test_health_is_bounded():
    score, _ = relationship_health(
        days_since_last_contact=None, open_commitments=5, overdue_commitments=5, support_tickets_open=9
    )
    assert 0.0 <= score <= 1.0


def test_priority_prefers_fit_and_recency():
    hot = sales_priority(icp_fit=0.9, recency_days=1, attempts=3, deal_value=80_000, stage_weight=0.8)
    cold = sales_priority(icp_fit=0.2, recency_days=29, attempts=0, deal_value=0, stage_weight=0.1)
    assert hot > cold


def test_retention_cutoff():
    now = datetime(2026, 11, 22)
    assert (now - retention_cutoff(now, 30)).days == 30
    assert retention_cutoff(now, -5) == now


def test_account_contact_entities_are_separate():
    from aios.db.models import Base

    account = Account(org_id="o", name="ACME", cnpj="12345678000199")
    event = InteractionEvent(org_id="o", account_id="a", contact_id="c", summary="call")
    assert account.cnpj == "12345678000199"
    assert event.contact_id == "c"
    for name in ("crm_accounts", "crm_contacts", "crm_interactions"):
        assert name in Base.metadata.tables


def test_deal_entity_kind_is_derived():
    class D: stage = "mql"
    assert deal_entity_kind(D()) == "lead"
    D.stage = "sql"
    assert deal_entity_kind(D()) == "opportunity"
    D.stage = "closed_won"
    assert deal_entity_kind(D()) == "closed_deal"


def test_deal_360_payload_exposes_heuristic_link_labels():
    class D:
        id = "d1"; stage = "mql"; lead_name = "Ana"; lead_email = "a@x"; lead_phone = ""
        value = 0; currency = "BRL"; score = 0; source = "manual"; agent_id = None
        team_id = None; pipeline = "default"; close_date = None; probability = 0
        extra_data = {"company": "ACME"}

    p = deal_360_payload(D(), account=None, contact=None)
    assert p["account_link"]["kind"] == "none"
    assert p["account_link"]["authoritative"] is False
    assert "No schema FK" in p["account_link"]["note"]
    assert p["contact_link"]["kind"] == "none"
    assert "legacy_extra_data_note" in p
    assert p["legacy_extra_keys"] == ["company"]


async def test_account_contact_interaction_endpoints_tenant_scoped(test_session):
    org = Organization(name="A", slug="a", extra_data={"crm_enabled": True})
    org2 = Organization(name="B", slug="b", extra_data={"crm_enabled": True})
    test_session.add_all([org, org2])
    await test_session.flush()
    acc = Account(org_id=org.id, name="ACME")
    acc2 = Account(org_id=org2.id, name="OTHER")
    c = Contact(org_id=org.id, name="Ana", email="ana@acme.com", account_id=acc.id)
    deal = CrmDeal(org_id=org.id, lead_name="Ana", lead_email="ana@acme.com", stage="mql")
    test_session.add_all([acc, acc2, c, deal])
    await test_session.commit()

    from httpx import ASGITransport, AsyncClient
    from aios.main import app
    from aios.api.deps import get_current_user, get_db_backend, get_org_id
    from aios.db.backends.sqlalchemy_backend import SQLAlchemyBackend

    async def _db():
        yield SQLAlchemyBackend(test_session)

    async def _org():
        return org.id

    class U:
        role = "admin"
        id = "u1"

    async def _user():
        return U()

    app.dependency_overrides[get_db_backend] = _db
    app.dependency_overrides[get_org_id] = _org
    app.dependency_overrides[get_current_user] = _user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/crm/accounts")
            assert r.status_code == 200
            names = [x["name"] for x in r.json()]
            assert "ACME" in names and "OTHER" not in names

            r = await client.post("/api/crm/contacts", json={"name": "Bob", "email": "bob@acme.com", "account_id": acc.id})
            assert r.status_code == 200
            r = await client.post("/api/crm/interactions", json={"deal_id": deal.id, "account_id": acc.id, "contact_id": c.id, "summary": "call", "channel": "phone"})
            assert r.status_code == 200
            body = r.json()
            assert body["deal_id"] == deal.id

            r = await client.get(f"/api/crm/interactions?deal_id={deal.id}")
            assert r.status_code == 200
            assert any(x["summary"] == "call" for x in r.json())

            r = await client.get("/api/crm/360/overview")
            assert r.status_code == 200
            ov = r.json()
            assert ov["available"]["customer_360_read"] is True
            assert ov["available"]["command_center"] is False
            assert ov["gaps"]["deal_account_fk"]["present"] is False
            assert ov["gaps"]["deal_contact_fk"]["present"] is False
            assert "docs/CRM_SCHEMA_GAPS.md" in ov["gaps"]["deal_account_fk"]["doc"]
            assert any("heuristic" in n.lower() for n in ov["notes"])

            r = await client.get(f"/api/crm/360/deals/{deal.id}")
            assert r.status_code == 200
            d360 = r.json()
            assert d360["account_link"]["kind"] == "none"  # no name/cnpj/extra_data match
            assert d360["account_link"]["authoritative"] is False
            assert d360["contact_link"]["kind"] == "heuristic"
            assert d360["contact_link"]["source"] == "lead_email_exact"
            assert "No schema FK" in d360["account_link"]["note"]

            r = await client.get(f"/api/crm/360/accounts/{acc.id}")
            assert r.status_code == 200
            a360 = r.json()
            assert a360["read_only"] is True
            assert a360["schema_gap"]["deal_account_fk"] is False
            assert "docs/CRM_SCHEMA_GAPS.md" in a360["schema_gap"]["doc"]

            r = await client.get(f"/api/crm/360/contacts/{c.id}")
            assert r.status_code == 200
            c360 = r.json()
            assert c360["read_only"] is True
            assert c360["schema_gap"]["deal_contact_fk"] is False
            assert any(x["id"] == deal.id for x in c360["deals"])
    finally:
        app.dependency_overrides.clear()
