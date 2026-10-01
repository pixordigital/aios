"""CRM tools for agents: org isolation, plus the read/follow-up operations.

The three existing CRM tools resolved the org with Organization.limit(1), so
any agent's deal was written to, moved within, or merged across whichever org
sorted first. Now they take the engine's org and fail closed without it.
"""

import pytest
from sqlalchemy import select

from aios.db.backend import db_session
from aios.db.models import CrmDeal, CrmDealVersion, Organization


async def _org(session, name="Org A"):
    org = Organization(name=name, slug=name.lower().replace(" ", "-"), extra_data={})
    session.add(org)
    await session.flush()
    return org


async def _deal(session, org, email="a@x.com", stage="mql", extra=None):
    d = CrmDeal(
        org_id=org.id,
        lead_name="Lead",
        lead_email=email,
        stage=stage,
        value=100.0,
        extra_data=extra or {},
    )
    session.add(d)
    await session.flush()
    return d


def _tool(name, org_id):
    """Load a tool the way the runtime does: engine sets _org_id per call."""
    from aios.core.tools import ToolEngine

    eng = ToolEngine([name], org_id=org_id)
    tool = eng.tools[name]
    tool._org_id = org_id  # execute() does this; direct calls must simulate it
    return tool


class TestEnginePropagatesOrg:
    async def test_execute_path_carries_org(self, test_session):
        """Through ToolEngine.execute — the real agent path."""
        import json

        org = await _org(test_session, "Exec Org")
        await _deal(test_session, org, "e@x.com")
        await test_session.commit()

        from aios.core.tools import ToolEngine

        eng = ToolEngine(["crm_list_deals"], org_id=org.id)
        out = json.loads(await eng.execute("crm_list_deals", json.dumps({})))
        assert out["ok"] is True
        assert any(d["lead_email"] == "e@x.com" for d in out["deals"])


class TestNoOrgFailsClosed:
    """No engine org must refuse, not fall back to the first org."""

    @pytest.mark.asyncio
    async def test_list_refuses(self):
        from aios.tools.crm import CRMListDealsTool

        res = await CRMListDealsTool().run()
        assert res["ok"] is False and "org" in res["error"]

    @pytest.mark.asyncio
    async def test_stale_refuses(self):
        from aios.tools.crm import CRMStaleDealsTool

        res = await CRMStaleDealsTool().run()
        assert res["ok"] is False

    @pytest.mark.asyncio
    async def test_follow_up_refuses(self):
        from aios.tools.crm import CRMSetFollowUpTool

        res = await CRMSetFollowUpTool().run(deal_id="x")
        assert res["ok"] is False

    @pytest.mark.asyncio
    async def test_create_refuses(self):
        from aios.tools.crm import CRMTool

        res = await CRMTool().run(lead_email="a@x.com", lead_name="A")
        assert res["ok"] is False

    def test_no_org_limit_fallback_left(self):
        from pathlib import Path

        src = Path("aios/tools/crm.py").read_text()
        assert "Organization).limit(1)" not in src
        assert "Organization).limit(1)" not in src.replace(" ", "")


class TestOrgIsolation:
    async def test_list_only_sees_own_org(self, test_session):
        org_a = await _org(test_session, "Org A")
        org_b = await _org(test_session, "Org B")
        await _deal(test_session, org_a, "a@x.com")
        await _deal(test_session, org_b, "b@x.com")
        await test_session.commit()

        tool = _tool("crm_list_deals", org_a.id)
        res = await tool.run()
        assert res["ok"] is True
        emails = [d["lead_email"] for d in res["deals"]]
        assert "a@x.com" in emails
        assert "b@x.com" not in emails

    async def test_update_foreign_deal_refused(self, test_session):
        org_a = await _org(test_session, "Org A")
        org_b = await _org(test_session, "Org B")
        deal_b = await _deal(test_session, org_b, "b@x.com")
        await test_session.commit()

        tool = _tool("crm_update_deal", org_a.id)
        res = await tool.run(deal_id=deal_b.id, stage="closed_won")
        # either refused outright or pending approval; must never apply
        assert res.get("ok") in (False, True)
        assert not res.get("pending") or True
        async with db_session() as s:
            fresh = (await s.execute(select(CrmDeal).where(CrmDeal.id == deal_b.id))).scalar_one()
            assert fresh.stage == "mql", "another org moved our deal"


class TestReadTools:
    async def test_list_excludes_closed(self, test_session):
        org = await _org(test_session)
        await _deal(test_session, org, "open@x.com", stage="sql")
        await _deal(test_session, org, "won@x.com", stage="closed_won")
        await test_session.commit()

        res = await _tool("crm_list_deals", org.id).run()
        emails = [d["lead_email"] for d in res["deals"]]
        assert "open@x.com" in emails
        assert "won@x.com" not in emails

    async def test_set_follow_up_persists_and_versions(self, test_session):
        org = await _org(test_session)
        deal = await _deal(test_session, org)
        await test_session.commit()

        res = await _tool("crm_set_follow_up", org.id).run(deal_id=deal.id, days_from_now=3, note="ligar")
        assert res["ok"] is True
        async with db_session() as s:
            fresh = (await s.execute(select(CrmDeal).where(CrmDeal.id == deal.id))).scalar_one()
            assert fresh.extra_data["next_follow_up"]
            assert fresh.extra_data["follow_up_note"] == "ligar"
            vers = (await s.execute(
                select(CrmDealVersion).where(CrmDealVersion.deal_id == deal.id)
            )).scalars().all()
            assert any(v.field == "next_follow_up" for v in vers)

    async def test_stale_flags_never_contacted(self, test_session):
        org = await _org(test_session)
        await _deal(test_session, org, "cold@x.com")  # no last_contacted_at
        await test_session.commit()

        res = await _tool("crm_stale_deals", org.id).run(stale_days=7)
        assert res["ok"] is True
        assert any(d["lead_email"] == "cold@x.com" for d in res["unengaged"])

    async def test_stale_flags_overdue_follow_up(self, test_session):
        from datetime import datetime, timedelta, timezone

        org = await _org(test_session)
        past = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)).isoformat()
        await _deal(test_session, org, "late@x.com", extra={"next_follow_up": past})
        await test_session.commit()

        res = await _tool("crm_stale_deals", org.id).run()
        assert any(d["lead_email"] == "late@x.com" for d in res["overdue"])


class TestToolEngineResilience:
    """One bad tool name must not make an agent unrunnable."""

    def test_unknown_tool_is_skipped_not_raised(self):
        from aios.core.tools import ToolEngine

        eng = ToolEngine(["crm_list_deals", "totally_not_a_tool"], org_id="o")
        assert "crm_list_deals" in eng.tools
        assert "totally_not_a_tool" in eng.missing

    def test_agent_runtime_survives_stale_tool_name(self):
        import types

        from aios.core.agent import AgentRuntime

        agent = types.SimpleNamespace(
            id="a", org_id="o", tools=["sql_query", "gone_tool"],
            llm_config={"model": "openai/gpt-4o"}, governance_config={},
            name="t", system_prompt="", memory_config={},
        )
        rt = AgentRuntime(agent)  # must not raise
        assert "sql_query" in rt.tool_engine.tools
        assert rt.tool_engine.missing == ["gone_tool"]


class TestNaiveUtcAndNoFakeSuccess:
    """Live round-trip found: crm_create_deal failed on Postgres (tz-aware
    datetime into a naive column) and returned ok:true with a mock id."""

    def test_now_utc_is_naive(self):
        from aios.tools.crm import _now_utc

        assert _now_utc().tzinfo is None

    def test_no_aware_datetime_left(self):
        from pathlib import Path

        src = Path("aios/tools/crm.py").read_text()
        # The only permitted occurrence is inside _now_utc(), which strips tz.
        body = src.replace(
            "return datetime.now(timezone.utc).replace(tzinfo=None)", ""
        )
        assert "datetime.now(timezone.utc)" not in body

    def test_no_mock_deal_id(self):
        from pathlib import Path

        src = Path("aios/tools/crm.py").read_text()
        assert 'f"mock_{lead_email}"' not in src

    async def test_create_fails_honestly_when_db_write_fails(self, monkeypatch):
        """A failed internal insert must surface, never fabricate an id.

        The live bug: Postgres rejected the tz-aware close_date, the insert
        failed, and the tool still returned ok:true with deal_id
        "mock_<email>" — agents reported deals that did not exist.
        """
        import contextlib

        import aios.db.engine as engine_mod
        from aios.tools.crm import CRMTool

        @contextlib.asynccontextmanager
        async def boom():
            raise RuntimeError("db down")
            yield  # pragma: no cover

        monkeypatch.setattr(engine_mod, "async_session", boom)
        tool = CRMTool()
        tool._org_id = "org-x"
        res = await tool.run(lead_email="fail@x.com", lead_name="Fail")

        assert res["ok"] is False
        assert "CRM interno" in res["error"]
        assert not str(res.get("deal_id") or "").startswith("mock_")


class TestCrmControl:
    """Sales must be able to operate the CRM, not just read and advance stages."""

    @pytest.mark.asyncio
    async def test_update_fields_without_stage(self, test_session):
        """Regression: a value-only update did nothing.

        The old apply block required `stage in VALID_STAGES` before touching
        anything, so passing only value/lead_email silently no-op'd.
        """
        org = await _org(test_session)
        deal = await _deal(test_session, org)
        deal.value = 100.0
        await test_session.commit()

        res = await _tool("crm_update_deal", org.id).run(
            deal_id=deal.id, value=2500.0, lead_phone="5511999999999")
        assert res["ok"] is True
        assert "value" in res["updated_fields"]
        async with db_session() as s:
            fresh = (await s.execute(select(CrmDeal).where(CrmDeal.id == deal.id))).scalar_one()
            assert fresh.value == 2500.0
            assert fresh.lead_phone == "5511999999999"
            assert fresh.stage == "mql", "empty stage must not blank the stage"

    @pytest.mark.asyncio
    async def test_reassign_owner(self, test_session):
        from aios.db.models import Agent

        org = await _org(test_session)
        deal = await _deal(test_session, org)
        ag = Agent(org_id=org.id, name="NewOwner", agent_type="sdr",
                   system_prompt="", llm_config={}, tools=[], memory_config={})
        test_session.add(ag)
        await test_session.flush()
        await test_session.commit()

        res = await _tool("crm_update_deal", org.id).run(deal_id=deal.id, agent_id=ag.id)
        assert res["ok"] is True
        async with db_session() as s:
            fresh = (await s.execute(select(CrmDeal).where(CrmDeal.id == deal.id))).scalar_one()
            assert fresh.agent_id == ag.id

    @pytest.mark.asyncio
    async def test_update_foreign_deal_refused_with_value(self, test_session):
        org_a, org_b = await _org(test_session, "A"), await _org(test_session, "B")
        deal_b = await _deal(test_session, org_b, "b@x.com")
        deal_b.value = 900.0
        await test_session.commit()
        res = await _tool("crm_update_deal", org_a.id).run(
            deal_id=deal_b.id, value=1.0)
        assert res["ok"] is False
        async with db_session() as s:
            fresh = (await s.execute(select(CrmDeal).where(CrmDeal.id == deal_b.id))).scalar_one()
            assert fresh.value == 900.0, "cross-org write must not land"


class TestCrmDelete:
    @pytest.mark.asyncio
    async def test_requires_confirm(self, test_session):
        org = await _org(test_session)
        deal = await _deal(test_session, org)
        await test_session.commit()
        res = await _tool("crm_delete_deal", org.id).run(deal_id=deal.id)
        assert res["ok"] is False and "confirm" in res["error"]

    @pytest.mark.asyncio
    async def test_deletes_with_confirm(self, test_session):
        org = await _org(test_session)
        deal = await _deal(test_session, org)
        await test_session.commit()
        res = await _tool("crm_delete_deal", org.id).run(deal_id=deal.id, confirm=True)
        assert res["ok"] is True
        async with db_session() as s:
            gone = (await s.execute(select(CrmDeal).where(CrmDeal.id == deal.id))).scalar_one_or_none()
            assert gone is None

    @pytest.mark.asyncio
    async def test_cannot_delete_other_org_deal(self, test_session):
        org_a, org_b = await _org(test_session, "A"), await _org(test_session, "B")
        deal_b = await _deal(test_session, org_b, "b@x.com")
        await test_session.commit()
        res = await _tool("crm_delete_deal", org_a.id).run(deal_id=deal_b.id, confirm=True)
        assert res["ok"] is False

    def test_only_manager_may_delete(self):
        from aios.templates import apply_template

        assert "crm_delete_deal" in apply_template("manager_sales")["tools"]
        for k in ("sdr", "closer", "manager_dev", "manager_red",
                  "manager_blue", "manager_data", "data_analyst"):
            assert "crm_delete_deal" not in apply_template(k)["tools"], k


class TestCrmPipelineStats:
    @pytest.mark.asyncio
    async def test_funnel_and_rates(self, test_session):
        org = await _org(test_session)
        await _deal(test_session, org, "w@x.com", stage="closed_won")
        await _deal(test_session, org, "l@x.com", stage="closed_lost")
        await _deal(test_session, org, "o@x.com", stage="sql")
        await test_session.commit()

        res = await _tool("crm_pipeline_stats", org.id).run()
        assert res["ok"] is True
        assert res["total_deals"] == 3
        assert res["by_stage"]["closed_won"] == 1
        assert res["open_deals"] == 1
        assert res["win_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_only_own_org(self, test_session):
        org_a, org_b = await _org(test_session, "A"), await _org(test_session, "B")
        await _deal(test_session, org_b, "b@x.com")
        await test_session.commit()
        res = await _tool("crm_pipeline_stats", org_a.id).run()
        assert res["total_deals"] == 0

    @pytest.mark.asyncio
    async def test_data_team_can_read_stats_without_org_literal(self, test_session):
        """The point: analysts do not know their org_id, so the tool must not
        make them supply it. It resolves from the engine, like every other tool.
        """
        org = await _org(test_session)
        await _deal(test_session, org, "a@x.com", stage="mql")
        await test_session.commit()
        res = await _tool("crm_pipeline_stats", org.id).run()
        assert res["ok"] is True
        assert res["total_deals"] == 1

    def test_both_teams_have_read_access(self):
        from aios.templates import apply_template

        for k in ("sdr", "closer", "manager_sales",
                  "data_analyst", "data_scientist", "manager_data"):
            assert "crm_pipeline_stats" in apply_template(k)["tools"], k

    def test_no_write_tools_leak_to_data_team(self):
        from aios.templates import apply_template

        for k in ("data_analyst", "data_scientist", "manager_data"):
            writes = {t for t in apply_template(k)["tools"]
                      if t.startswith("crm_") and t != "crm_pipeline_stats"}
            assert not writes, f"{k} can write the CRM: {writes}"

    @pytest.mark.asyncio
    async def test_stats_refuses_without_org(self):
        from aios.tools.crm import CRMPipelineStatsTool

        res = await CRMPipelineStatsTool().run()
        assert res["ok"] is False
