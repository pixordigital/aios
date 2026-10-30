"""Lead research pipeline: Prospector saves, manager reviews, SDR receives.

Pins the three properties the sales flow depends on: org isolation, dedupe by
contact/site, and that "sent to SDR" actually moves the lead into the CRM
pipeline (stage mql) instead of leaving it parked in prospection.
"""

import types

import pytest
from sqlalchemy import select

from aios.db.models import Agent, CrmDeal, Organization


async def _org(session, name="Lead Org"):
    org = Organization(name=name, slug=name.lower().replace(" ", "-"), extra_data={})
    session.add(org)
    await session.flush()
    return org


def _lead_tool(name, org_id):
    from aios.tools.leads import LeadListTool, LeadReviewTool, LeadSaveTool
    tool = {"save": LeadSaveTool, "list": LeadListTool, "review": LeadReviewTool}[name]()
    tool._org_id = org_id
    tool._agent_id = "finder-1"
    return tool


ICP = "Clínicas odontológicas em São Paulo, 11-50 funcionários"


class TestLeadSave:
    async def test_saves_as_prospection_lead(self, test_session):
        org = await _org(test_session)
        await test_session.commit()

        res = await _lead_tool("save", org.id).run(
            name="Odonto Sorriso", email="contato@sorriso.com.br",
            website="https://sorriso.com.br", industry="Odontologia",
            location="São Paulo, SP", company_size="11-50", fit_score=82,
            icp=ICP, source_url="https://sorriso.com.br/contato",
        )
        assert res["ok"] and res["duplicate"] is False
        row = (await test_session.execute(
            select(CrmDeal).where(CrmDeal.id == res["lead"]["lead_id"])
        )).scalar_one()
        assert row.org_id == org.id
        assert row.source == "lead_finder"
        assert row.stage == "prospection"
        assert row.score == 82
        assert row.extra_data["lead_status"] == "new"

    async def test_dedupes_same_email(self, test_session):
        org = await _org(test_session)
        await test_session.commit()
        tool = _lead_tool("save", org.id)
        first = await tool.run(name="A", email="a@x.com", icp=ICP)
        second = await tool.run(name="A clone", email="A@X.com", icp=ICP)
        assert first["ok"] and second["duplicate"] is True
        assert second["lead"]["lead_id"] == first["lead"]["lead_id"]

    async def test_requires_a_channel(self, test_session):
        org = await _org(test_session)
        await test_session.commit()
        res = await _lead_tool("save", org.id).run(name="No contact", icp=ICP)
        assert res["ok"] is False and "email" in res["error"]


class TestOrgIsolation:
    async def test_list_never_crosses_org(self, test_session):
        a = await _org(test_session, "Org A")
        b = await _org(test_session, "Org B")
        await test_session.commit()
        await _lead_tool("save", a.id).run(name="Lead A", email="a@a.com", icp=ICP)
        await _lead_tool("save", b.id).run(name="Lead B", email="b@b.com", icp=ICP)

        out = await _lead_tool("list", a.id).run()
        assert [l["name"] for l in out["leads"]] == ["Lead A"]

    async def test_review_refuses_foreign_lead(self, test_session):
        a = await _org(test_session, "Org A")
        b = await _org(test_session, "Org B")
        await test_session.commit()
        saved = await _lead_tool("save", b.id).run(name="B", email="b@b.com", icp=ICP)

        res = await _lead_tool("review", a.id).run(
            lead_ids=[saved["lead"]["lead_id"]], status="approved"
        )
        assert res["ok"] is True and res["changed"] == []
        assert res["skipped"] == [saved["lead"]["lead_id"]]


class TestReviewAndHandoff:
    async def test_send_to_sdr_moves_to_mql_and_assigns(self, test_session):
        org = await _org(test_session)
        sdr = Agent(org_id=org.id, name="SDR 1", agent_type="sdr", status="active")
        test_session.add(sdr)
        await test_session.commit()
        saved = await _lead_tool("save", org.id).run(
            name="Lead", email="l@x.com", icp=ICP
        )

        res = await _lead_tool("review", org.id).run(
            lead_ids=[saved["lead"]["lead_id"]], status="sent_to_sdr",
            sdr_agent_id=sdr.id, reason="ICP ok",
        )
        assert res["ok"] and res["changed"] == [saved["lead"]["lead_id"]]
        row = (await test_session.execute(
            select(CrmDeal).where(CrmDeal.id == saved["lead"]["lead_id"])
        )).scalar_one()
        assert row.stage == "mql"
        assert row.agent_id == sdr.id
        assert row.extra_data["lead_status"] == "sent_to_sdr"

    async def test_reject_keeps_stage(self, test_session):
        org = await _org(test_session)
        await test_session.commit()
        saved = await _lead_tool("save", org.id).run(name="L", email="l@x.com", icp=ICP)
        await _lead_tool("review", org.id).run(
            lead_ids=[saved["lead"]["lead_id"]], status="rejected"
        )
        row = (await test_session.execute(
            select(CrmDeal).where(CrmDeal.id == saved["lead"]["lead_id"])
        )).scalar_one()
        assert row.stage == "prospection"
        assert row.extra_data["lead_status"] == "rejected"


class TestTemplate:
    def test_lead_finder_is_registered_with_save_tool(self):
        from aios.templates import TEMPLATES
        t = TEMPLATES["lead_finder"]
        assert t["agent_type"] == "lead_finder"
        assert "lead_save" in t["tools"] and "web_search" in t["tools"]
        assert "lead_review" in TEMPLATES["manager_sales"]["tools"]

    async def test_dashboard_renders_leads(self, test_session):
        import aios.dashboard.app as app_mod

        org = Organization(name="Dash Org", slug="dash-org", extra_data={})
        test_session.add(org)
        await test_session.flush()
        test_session.add(CrmDeal(
            org_id=org.id, lead_name="Visible Lead", lead_email="v@x.com",
            stage="prospection", score=77, source="lead_finder",
            extra_data={"lead_status": "new", "batch": ICP, "industry": "Odontologia"},
        ))
        await test_session.commit()

        req = types.SimpleNamespace(
            state=types.SimpleNamespace(org_id=org.id),
            url=types.SimpleNamespace(path="/dashboard/leads", query=""),
        )
        html = await app_mod.leads_page(req)
        assert "Visible Lead" in html and "Odontologia" in html
        assert "Enviar ao SDR" in html

    async def test_dashboard_send_moves_selected_to_sdr(self, test_session):
        import aios.dashboard.app as app_mod

        org = await _org(test_session, "Send Org")
        sdr = Agent(org_id=org.id, name="SDR", agent_type="sdr", status="active")
        test_session.add(sdr)
        await test_session.commit()
        saved = await _lead_tool("save", org.id).run(name="L", email="l@x.com", icp=ICP)

        req = types.SimpleNamespace(state=types.SimpleNamespace(org_id=org.id))
        await app_mod.leads_send(req, ids=saved["lead"]["lead_id"], sdr_agent_id=sdr.id)

        row = (await test_session.execute(
            select(CrmDeal).where(CrmDeal.id == saved["lead"]["lead_id"])
        )).scalar_one()
        assert row.stage == "mql" and row.agent_id == sdr.id
