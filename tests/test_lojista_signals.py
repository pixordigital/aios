"""Lojista wizard + solutions + sinais-lite queue."""

import pytest
from httpx import AsyncClient
import jwt
from datetime import datetime, timedelta, timezone
from aios.config import settings


def _cookie_for(user):
    return jwt.encode(
        {"sub": user.id, "org": user.org_id, "type": "access",
         "iat": datetime.now(timezone.utc),
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )


class TestSolutions:
    def test_three_packs(self):
        from aios.templates.solutions import SOLUTIONS, get_solution
        assert set(SOLUTIONS) == {"vender", "atender", "recuperar"}
        for key, s in SOLUTIONS.items():
            assert s["agent_type"] in ("sdr", "support")
            assert s["addon"] and s["tools"]

    def test_unknown_raises(self):
        import pytest as _p
        from aios.templates.solutions import get_solution
        with _p.raises(ValueError):
            get_solution("nada")


class TestSignals:
    def test_hot_inbound_scores_high(self):
        from aios.core.signals import timing_score
        from aios.db.models import CrmDeal
        d = CrmDeal(source="form", stage="sql", value=1000, extra_data={"attempts": 0})
        d.updated_at = datetime.now(timezone.utc)
        r = timing_score(d)
        assert r["timing"] >= 70

    def test_cold_stale_scores_low(self):
        from aios.core.signals import timing_score
        from aios.db.models import CrmDeal
        d = CrmDeal(source="lista_fria", stage="prospection", value=0, extra_data={"attempts": 8})
        d.updated_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        d.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        r = timing_score(d)
        assert r["timing"] <= 10

    def test_rank_skips_closed(self):
        from aios.core.signals import rank_queue
        from aios.db.models import CrmDeal
        now = datetime.now(timezone.utc)
        a = CrmDeal(source="form", stage="closed_won", value=0, extra_data={})
        a.updated_at = now
        b = CrmDeal(source="lista_fria", stage="prospection", value=0, extra_data={"attempts": 9})
        b.updated_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        c = CrmDeal(source="whatsapp", stage="mql", value=0, extra_data={"attempts": 0})
        c.updated_at = now
        ranked = rank_queue([a, b, c])
        assert [r["deal"] for r in ranked] == [c, b]


@pytest.mark.asyncio(loop_scope="function")
async def test_lojista_page_renders(async_client: AsyncClient, test_session, test_org, test_user):
    async_client.cookies.set("aios_token", _cookie_for(test_user))
    r = await async_client.get("/dashboard/lojista")
    assert r.status_code == 200
    assert "1 minuto" in r.text


REF = {"referer": "http://test/dashboard/lojista"}


@pytest.mark.asyncio(loop_scope="function")
async def test_lojista_bad_solution(async_client: AsyncClient, test_session, test_org, test_user):
    async_client.cookies.set("aios_token", _cookie_for(test_user))
    r = await async_client.post("/dashboard/lojista/create", headers=REF, data={"phone": "5511999999999", "solution": "nada", "business": "loja"})
    assert r.status_code == 200
    assert "Escolha" in r.text


@pytest.mark.asyncio(loop_scope="function")
async def test_lojista_bad_phone(async_client: AsyncClient, test_session, test_org, test_user):
    async_client.cookies.set("aios_token", _cookie_for(test_user))
    r = await async_client.post("/dashboard/lojista/create", headers=REF, data={"phone": "abc", "solution": "vender", "business": "loja"})
    assert r.status_code == 200
    assert "inválido" in r.text


@pytest.mark.asyncio(loop_scope="function")
async def test_lojista_create_303(async_client: AsyncClient, test_session, test_org, test_user):
    async_client.cookies.set("aios_token", _cookie_for(test_user))
    r = await async_client.post("/dashboard/lojista/create", headers=REF, data={"phone": "5511999999999", "solution": "atender", "business": "pizzaria"}, follow_redirects=False)
    assert r.status_code == 303
    from sqlalchemy import select
    from aios.db.models import Agent, ChannelConnection
    agents = (await test_session.execute(select(Agent).where(Agent.org_id == test_org.id))).scalars().all()
    assert any("pizzaria" in a.name for a in agents)
    chans = (await test_session.execute(select(ChannelConnection).where(ChannelConnection.org_id == test_org.id))).scalars().all()
    assert any(c.channel_type == "evolution" for c in chans)


class TestQueueApi:
    async def test_queue_requires_auth(self, async_client: AsyncClient):
        r = await async_client.get("/api/crm/queue")
        assert r.status_code == 401

    async def test_queue_gated_without_crm(self, auth_client: AsyncClient):
        r = await auth_client.get("/api/crm/queue")
        assert r.status_code == 402

    async def test_queue_ordered(self, auth_client: AsyncClient, test_session, test_org):
        from aios.db.models import CrmDeal
        org = await test_session.get(__import__("aios.db.models", fromlist=["Organization"]).Organization, test_org.id)
        org.extra_data = {"crm_enabled": True}
        await test_session.commit()
        now = datetime.now(timezone.utc)
        cold = CrmDeal(org_id=test_org.id, lead_name="Frio", source="lista_fria", stage="prospection", extra_data={"attempts": 9})
        hot = CrmDeal(org_id=test_org.id, lead_name="Quente", source="form", stage="sql", extra_data={"attempts": 0})
        test_session.add_all([cold, hot])
        await test_session.commit()
        # force recency
        cold.updated_at = datetime(2020, 1, 1)
        hot.updated_at = now
        await test_session.commit()
        r = await auth_client.get("/api/crm/queue")
        assert r.status_code == 200
        names = [d["lead_name"] for d in r.json()]
        assert names[0] == "Quente"
