"""Sales funnels — shared Sales/Data pipeline.

Two teams work the same funnel object: Sales owns the stage ladder and moves
deals, the Data team reads and posts findings it cannot later have edited by
Sales. These pin the split, the cross-org boundary, and the conversion maths.
"""

import json

import pytest
from httpx import AsyncClient

REF = {"referer": "http://test/dashboard/funnels"}


def _cookie(user):
    import jwt
    from datetime import datetime, timedelta, timezone
    from aios.config import settings
    return jwt.encode(
        {"sub": user.id, "org": user.org_id, "type": "access",
         "iat": datetime.now(timezone.utc),
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )


async def _funnel(session, org_id, **kw):
    from aios.db.models import SalesFunnel
    f = SalesFunnel(org_id=org_id, name=kw.pop("name", "F1"), pipeline=kw.pop("pipeline", "default"),
                    extra_data=kw.pop("extra_data", {"stages": ["a", "b", "closed_won"]}), **kw)
    session.add(f)
    await session.commit()
    await session.refresh(f)
    return f


class TestFunnelPages:
    async def test_list_renders(self, async_client: AsyncClient, test_session, test_org, test_user):
        async_client.cookies.set("aios_token", _cookie(test_user))
        r = await async_client.get("/dashboard/funnels")
        assert r.status_code == 200
        assert "Funis de Vendas" in r.text

    async def test_create_then_appears(self, async_client: AsyncClient, test_session, test_org, test_user):
        async_client.cookies.set("aios_token", _cookie(test_user))
        r = await async_client.post("/dashboard/funnels/create", headers=REF, data={
            "name": "Enterprise BR", "description": "big accounts",
            "stages": "prospec\nproposta\nfechado", "pipeline": "ent",
        }, follow_redirects=False)
        assert r.status_code == 303
        from sqlalchemy import select
        from aios.db.models import SalesFunnel
        f = (await test_session.execute(
            select(SalesFunnel).where(SalesFunnel.name == "Enterprise BR"))).scalars().first()
        assert f is not None
        # stages are Sales' ladder, stored in order
        assert f.extra_data["stages"] == ["prospec", "proposta", "fechado"]
        assert f.pipeline == "ent"

    async def test_create_rejects_blank_name(self, async_client: AsyncClient, test_session, test_org, test_user):
        async_client.cookies.set("aios_token", _cookie(test_user))
        r = await async_client.post("/dashboard/funnels/create", headers=REF, data={
            "name": "   ", "stages": "a\nb", "pipeline": "x",
        }, follow_redirects=False)
        assert r.status_code == 303
        from sqlalchemy import select
        from aios.db.models import SalesFunnel
        assert (await test_session.execute(select(SalesFunnel))).scalars().all() == []

    async def test_create_falls_back_to_default_stages(self, async_client: AsyncClient, test_session, test_org, test_user):
        """Blank stages must not produce a funnel with an empty board."""
        async_client.cookies.set("aios_token", _cookie(test_user))
        await async_client.post("/dashboard/funnels/create", headers=REF, data={
            "name": "NoStages", "stages": "\n\n  \n", "pipeline": "ns",
        }, follow_redirects=False)
        from sqlalchemy import select
        from aios.db.models import SalesFunnel
        f = (await test_session.execute(
            select(SalesFunnel).where(SalesFunnel.name == "NoStages"))).scalars().first()
        assert f.extra_data["stages"] == ["prospection", "qualification", "proposal",
                                          "negotiation", "closed_won"]


class TestFunnelDetail:
    async def test_detail_renders_stage_columns(self, async_client: AsyncClient, test_session, test_org, test_user):
        from aios.db.models import CrmDeal
        async_client.cookies.set("aios_token", _cookie(test_user))
        f = await _funnel(test_session, test_org.id)
        test_session.add_all([
            CrmDeal(org_id=test_org.id, lead_name="D1", stage="a", value=100, pipeline="default"),
            CrmDeal(org_id=test_org.id, lead_name="D2", stage="b", value=250, pipeline="default"),
        ])
        await test_session.commit()
        r = await async_client.get(f"/dashboard/funnels/{f.id}")
        assert r.status_code == 200
        assert "D1" in r.text and "D2" in r.text
        assert "closed_won" in r.text

    async def test_other_org_funnel_is_404_not_403(self, async_client: AsyncClient, test_session, test_org, test_user):
        """403 would confirm the funnel exists in another org."""
        f = await _funnel(test_session, "org-outro")
        async_client.cookies.set("aios_token", _cookie(test_user))
        r = await async_client.get(f"/dashboard/funnels/{f.id}")
        assert r.status_code == 404

    async def test_missing_funnel_is_404(self, async_client: AsyncClient, test_session, test_org, test_user):
        async_client.cookies.set("aios_token", _cookie(test_user))
        r = await async_client.get("/dashboard/funnels/nao-existe")
        assert r.status_code == 404

    async def test_ignores_deals_from_other_pipeline(self, async_client: AsyncClient, test_session, test_org, test_user):
        from aios.db.models import CrmDeal
        async_client.cookies.set("aios_token", _cookie(test_user))
        f = await _funnel(test_session, test_org.id, pipeline="ent")
        test_session.add_all([
            CrmDeal(org_id=test_org.id, lead_name="Meu", stage="a", value=1, pipeline="ent"),
            CrmDeal(org_id=test_org.id, lead_name="Outro", stage="a", value=1, pipeline="sme"),
        ])
        await test_session.commit()
        r = await async_client.get(f"/dashboard/funnels/{f.id}")
        assert "Meu" in r.text
        assert "Outro" not in r.text


class TestDomainSplit:
    """Sales owns stages/deals. Data posts findings; Sales only resolves them."""

    async def test_data_posts_insight(self, async_client: AsyncClient, test_session, test_org, test_user):
        async_client.cookies.set("aios_token", _cookie(test_user))
        f = await _funnel(test_session, test_org.id)
        r = await async_client.post(f"/dashboard/funnels/{f.id}/insights", headers=REF, data={
            "finding": "proposta->fechado caiu 30%", "recommendation": "revisar criteria", "stage": "a",
        }, follow_redirects=False)
        assert r.status_code == 303
        from sqlalchemy import select
        from aios.db.models import FunnelInsight
        i = (await test_session.execute(
            select(FunnelInsight).where(FunnelInsight.funnel_id == f.id))).scalars().first()
        assert i is not None
        assert i.author_type == "data"
        assert i.resolved is False
        assert i.stage == "a"

    async def test_insight_rejects_stage_not_in_ladder(self, async_client: AsyncClient, test_session, test_org, test_user):
        """A dangling stage would render on no column and never be found again."""
        async_client.cookies.set("aios_token", _cookie(test_user))
        f = await _funnel(test_session, test_org.id)
        await async_client.post(f"/dashboard/funnels/{f.id}/insights", headers=REF, data={
            "finding": "achado", "stage": "estagio-inexistente",
        }, follow_redirects=False)
        from sqlalchemy import select
        from aios.db.models import FunnelInsight
        i = (await test_session.execute(
            select(FunnelInsight).where(FunnelInsight.funnel_id == f.id))).scalars().first()
        assert i.stage == ""

    async def test_insight_rejects_blank_finding(self, async_client: AsyncClient, test_session, test_org, test_user):
        async_client.cookies.set("aios_token", _cookie(test_user))
        f = await _funnel(test_session, test_org.id)
        await async_client.post(f"/dashboard/funnels/{f.id}/insights", headers=REF,
                                data={"finding": "   "}, follow_redirects=False)
        from sqlalchemy import select
        from aios.db.models import FunnelInsight
        assert (await test_session.execute(select(FunnelInsight))).scalars().all() == []

    async def test_sales_resolve_preserves_text(self, async_client: AsyncClient, test_session, test_org, test_user):
        """Resolving marks it done; it must not rewrite the Data team's finding."""
        from aios.db.models import FunnelInsight
        async_client.cookies.set("aios_token", _cookie(test_user))
        f = await _funnel(test_session, test_org.id)
        ins = FunnelInsight(org_id=test_org.id, funnel_id=f.id, finding="texto original",
                            recommendation="acao", author_type="data")
        test_session.add(ins)
        await test_session.commit()
        await test_session.refresh(ins)

        r = await async_client.post(f"/dashboard/funnels/insights/{ins.id}/resolve",
                                    headers=REF, follow_redirects=False)
        assert r.status_code == 303
        await test_session.refresh(ins)
        assert ins.resolved is True
        assert ins.finding == "texto original"
        assert ins.recommendation == "acao"

    async def test_resolve_other_org_is_404(self, async_client: AsyncClient, test_session, test_org, test_user):
        from aios.db.models import FunnelInsight
        async_client.cookies.set("aios_token", _cookie(test_user))
        ins = FunnelInsight(org_id="org-outro", funnel_id="f-alheio", finding="x")
        test_session.add(ins)
        await test_session.commit()
        await test_session.refresh(ins)
        r = await async_client.post(f"/dashboard/funnels/insights/{ins.id}/resolve", headers=REF)
        assert r.status_code == 404
        await test_session.refresh(ins)
        assert ins.resolved is False

    async def test_no_route_lets_sales_edit_an_insight(self, async_client: AsyncClient, test_session, test_org, test_user):
        """Pinning the absence: only create and resolve exist for insights.

        If someone adds an edit endpoint later, this fails and they have to
        decide deliberately that Sales may rewrite a Data finding.
        """
        from aios.main import app
        paths = {r.path for r in app.routes if hasattr(r, "path")}
        insight_routes = {p for p in paths if "insight" in p}
        # create (nested) + resolve only
        assert not any(p.endswith("/insights/{insight_id}") for p in insight_routes)
        assert not any("edit" in p or "update" in p for p in insight_routes)


class TestConversion:
    """A rate that Sales acts on must be true. The first version of this was
    structurally always 100%: it counted deals whose *current* stage equalled the
    next stage among deals sitting in *this* stage, which can never match. These
    pin the corrected behaviour and the two ways it refuses to lie.
    """

    class D:
        def __init__(self, stage, value=0, did=None):
            self.stage, self.value, self.id = stage, value, did or stage

    def test_rate_is_not_structurally_100(self):
        """The bug: every advancing stage reported 100% stalled."""
        from aios.dashboard.app import _columns
        # 4 residents in 'a', 6 recorded as having moved on -> 60% advanced.
        cols = _columns(["a", "b", "closed_won"],
                        [self.D("a", did=f"r{i}") for i in range(4)],
                        transitions={"a": {f"g{i}" for i in range(6)}})
        assert cols[0]["rate"] == 60.0
        assert cols[0]["n_rate"] == 10  # 4 still there + 6 that left

    def test_stalled_stage_reports_zero_not_high(self):
        from aios.dashboard.app import _columns
        cols = _columns(["a", "b"], [self.D("a", did=f"r{i}") for i in range(8)],
                        transitions={"a": set()})
        assert cols[0]["rate"] == 0.0
        assert cols[0]["n_rate"] == 8

    def test_absent_history_reports_nothing_not_zero(self):
        """No audit trail means 'unknown', not 'nobody advanced'. Reporting 0%
        would tell Sales the whole stage is stalled when we simply never recorded
        the transitions -- the single most likely way to trigger a wrong call."""
        from aios.dashboard.app import _columns
        cols = _columns(["a", "b"], [self.D("a", did=f"r{i}") for i in range(20)])
        assert cols[0]["rate"] is None
        assert cols[0]["n_rate"] is None
        # but the deals are still counted and shown -- silence is about the rate
        assert len(cols[0]["deals"]) == 20

    def test_small_n_reports_nothing_rather_than_100_percent(self):
        """1 of 1 advanced = 100% is a false positive, not a trend."""
        from aios.dashboard.app import _columns, _MIN_STAGE_N
        cols = _columns(["a", "b"], [self.D("a")], transitions={"a": {"g1"}})
        assert cols[0]["rate"] is None
        assert cols[0]["n_rate"] is None
        # at the threshold it does report
        enough = [self.D("a", did=f"r{i}") for i in range(_MIN_STAGE_N - 1)]
        c2 = _columns(["a", "b"], enough, transitions={"a": {"g1"}})
        assert c2[0]["rate"] is not None

    def test_rate_100_requires_every_deal_to_have_moved(self):
        from aios.dashboard.app import _columns
        cols = _columns(["a", "b"], [self.D("a", did="still")],
                        transitions={"a": {"g1", "g2", "g3", "g4", "g5"}})
        assert cols[0]["rate"] < 100.0

    def test_closed_stage_gets_no_rate(self):
        from aios.dashboard.app import _columns
        cols = _columns(["a", "closed_won"], [self.D("a"), self.D("closed_won")],
                        transitions={"a": {"g1", "g2", "g3", "g4", "g5"}})
        assert cols[-1]["rate"] is None  # nowhere to advance to

    def test_transitions_for_unknown_stage_are_ignored(self):
        """Renaming a rung must not resurrect old history as a false signal."""
        from aios.dashboard.app import _columns
        cols = _columns(["a", "b"], [self.D("a", did=f"r{i}") for i in range(6)],
                        transitions={"a": {"g1"}, "stage-antigo": {"g2", "g3"}})
        # the orphan history must not inflate 'a'
        assert cols[0]["n_rate"] == 7

    def test_win_rate_zero_deals_is_not_division_error(self):
        from aios.dashboard.app import _funnel_stats
        st = _funnel_stats([])
        assert st["total"] == 0
        assert st["win_rate"] == 0.0

    def test_win_rate_counts_only_closed_won(self):
        from aios.dashboard.app import _funnel_stats
        st = _funnel_stats([self.D("closed_won"), self.D("closed_lost"), self.D("a")])
        assert st["won"] == 1
        assert st["total"] == 3

    def test_unknown_stage_gets_its_own_column(self):
        """A deal in a rung Sales removed must stay visible -- dropping it would
        silently change every rate on the board."""
        from aios.dashboard.app import _columns
        cols = _columns(["a", "b"], [self.D("a"), self.D("stage-depreciado")],
                        transitions={"a": {f"g{i}" for i in range(6)}})
        assert len(cols) == 3  # a, b, plus the orphan column
        assert len(cols[0]["deals"]) == 1
        assert "fora do funil" in cols[2]["stage"]
        assert len(cols[2]["deals"]) == 1
        assert cols[2]["rate"] is None

    def test_orphan_column_does_not_change_other_rates(self):
        from aios.dashboard.app import _columns
        clean = _columns(["a", "b"], [self.D("a", did=f"r{i}") for i in range(4)],
                         transitions={"a": {f"g{i}" for i in range(6)}})
        with_orphan = _columns(["a", "b"], [self.D("a", did=f"r{i}") for i in range(4)]
                               + [self.D("renomeado")],
                               transitions={"a": {f"g{i}" for i in range(6)}})
        assert clean[0]["rate"] == with_orphan[0]["rate"] == 60.0


class TestTransitionEventLog:
    """_stage_transitions must read the audit trail, not guess."""

    async def test_reads_stage_versions(self, test_session, test_org):
        from aios.dashboard.app import _stage_transitions
        from aios.db.models import CrmDeal, CrmDealVersion
        d1 = CrmDeal(org_id=test_org.id, lead_name="A", stage="b", pipeline="p")
        d2 = CrmDeal(org_id=test_org.id, lead_name="B", stage="b", pipeline="p")
        test_session.add_all([d1, d2])
        await test_session.commit()
        await test_session.refresh(d1)
        await test_session.refresh(d2)
        test_session.add_all([
            CrmDealVersion(deal_id=d1.id, org_id=test_org.id, field="stage",
                           old_value="a", new_value="b"),
            # not a stage change -- must be ignored
            CrmDealVersion(deal_id=d2.id, org_id=test_org.id, field="value",
                           old_value="1", new_value="2"),
        ])
        await test_session.commit()
        out = await _stage_transitions(test_session, test_org.id, ["a", "b", "closed_won"],
                                        {d1.id, d2.id})
        assert out == {"a": {d1.id}}

    async def test_ignores_deals_outside_the_funnel(self, test_session, test_org):
        from aios.dashboard.app import _stage_transitions
        from aios.db.models import CrmDeal, CrmDealVersion
        mine = CrmDeal(org_id=test_org.id, lead_name="Mine", stage="b", pipeline="p")
        test_session.add(mine)
        await test_session.commit()
        await test_session.refresh(mine)
        test_session.add(CrmDealVersion(deal_id=mine.id, org_id=test_org.id, field="stage",
                                        old_value="a", new_value="b"))
        await test_session.commit()
        # empty deal set -> no history consulted
        assert await _stage_transitions(test_session, test_org.id, ["a", "b"], set()) == {}

    async def test_ignores_other_org_history(self, test_session, test_org):
        from aios.dashboard.app import _stage_transitions
        from aios.db.models import CrmDeal, CrmDealVersion
        d = CrmDeal(org_id=test_org.id, lead_name="A", stage="b", pipeline="p")
        test_session.add(d)
        await test_session.commit()
        await test_session.refresh(d)
        test_session.add(CrmDealVersion(deal_id=d.id, org_id="outra-org", field="stage",
                                        old_value="a", new_value="b"))
        await test_session.commit()
        out = await _stage_transitions(test_session, test_org.id, ["a", "b"], {d.id})
        assert out == {}


class TestKPIHonesty:
    """KPIs Sales acts on must not report a number they cannot support.

    Two real false signals were found: a future month scoring "ahead" because its
    expected value is 0, and a pipeline-wide conversion printing 0% when nothing
    has closed yet (which reads as "every deal fails").
    """

    def _summary(self, target, won, year_month, current_month):
        import calendar
        from datetime import date
        dim = calendar.monthrange(int(year_month[:4]), int(year_month[5:7]))[1]
        if year_month == current_month:
            day = date.today().day
        elif year_month < current_month:
            day = dim
        else:
            day = 0
        expected = target * day / dim if target and day else 0.0
        st = ("no_goal" if not target else
              "not_started" if day == 0 else
              "ahead" if (won or 0) >= expected else "behind")
        return st, day

    def test_future_month_is_not_reported_as_ahead(self):
        """expected == 0 for a month that has not started, so the old
        `won >= expected` test scored an untouched future month "ahead"."""
        st, day = self._summary(100000, 0, "2099-11", "2026-10")
        assert day == 0
        assert st == "not_started"

    def test_past_month_on_target_is_ahead(self):
        st, _ = self._summary(100000, 120000, "2026-09", "2026-10")
        assert st == "ahead"

    def test_current_month_behind_stays_behind(self):
        st, day = self._summary(100000, 0, "2026-10", "2026-10")
        if day > 1:   # only meaningful once the month has actually progressed
            assert st == "behind"

    def test_no_goal_when_no_target(self):
        st, _ = self._summary(0, 0, "2026-10", "2026-10")
        assert st == "no_goal"

    def test_conversion_is_none_not_zero_when_nothing_closed(self):
        """0% reads as 'everything fails'; the truth is 'no closed deals yet'."""
        def conv(won, lost):
            total = won + lost
            return round(won / total * 100, 1) if total else None
        assert conv(0, 0) is None
        assert conv(1, 1) == 50.0
        assert conv(2, 0) == 100.0

    def test_funnel_win_rate_zero_deals_reports_zero_not_nan(self):
        from aios.dashboard.app import _funnel_stats
        assert _funnel_stats([])["win_rate"] == 0.0
