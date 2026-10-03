"""The daily board, and the SDR -> CRM handoff that feeds it.

Two gaps, both about continuity rather than capability:

- `signals.rank_queue` built a "fila do dia" for the dashboard, and no agent ever
  worked it. An agent with no event subscriptions did nothing at all, forever.
- An answered WhatsApp conversation left nothing in the CRM. The lead only
  reached it if the agent happened to call `crm_create_deal`, and nothing
  recorded what was said, so the next agent inherited a name and a phone number
  and no context.
"""

from datetime import datetime, timedelta, timezone

import contextlib

import pytest
from sqlalchemy import select

from aios.db.models import Agent, CrmDeal, CrmDealVersion, Organization

from aios.db.engine import async_session


@contextlib.asynccontextmanager
async def _cookie(client, user):
    """Dashboard routes authenticate by cookie, not bearer.

    Encoded exactly like the `auth_headers` fixture so both credentials resolve
    to the same user and org. A cookie minted for a different org reads a
    different organization and every assertion silently passes against nothing.
    """
    import jwt
    from datetime import datetime, timedelta, timezone

    from aios.api.deps import COOKIE_NAME

    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": user.id,
            "org": user.org_id,
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=60),
        },
        "test-secret",
        algorithm="HS256",
    )
    client.cookies.set(COOKIE_NAME, token)
    try:
        yield
    finally:
        client.cookies.clear()


async def _org(name: str) -> str:
    from aios.db.engine import async_session

    async with async_session() as sess:
        o = Organization(name=name, slug=name)
        sess.add(o)
        await sess.commit()
        return o.id


async def _agent(org_id: str, name: str, agent_type: str = "closer", status: str = "active", **extra):
    from aios.db.engine import async_session

    async with async_session() as sess:
        a = Agent(org_id=org_id, name=name, agent_type=agent_type, status=status, extra_data=extra)
        sess.add(a)
        await sess.commit()
        return a.id


async def _enable_workday(org_id: str) -> None:
    """Flip the org master switch on, as the dashboard toggle would."""
    from aios.db.engine import async_session

    async with async_session() as sess:
        o = await sess.get(Organization, org_id)
        o.extra_data = {**(o.extra_data or {}), "workday_enabled": True}
        await sess.commit()


async def _deal(org_id: str, agent_id: str | None, **kw):
    from aios.db.engine import async_session

    fields = dict(
        org_id=org_id,
        lead_name=kw.pop("lead_name", "Lead"),
        lead_phone=kw.pop("lead_phone", ""),
        stage=kw.pop("stage", "opportunity"),
        value=kw.pop("value", 1000.0),
        source=kw.pop("source", "whatsapp"),
    )
    fields.update(kw)
    async with async_session() as sess:
        d = CrmDeal(agent_id=agent_id, **fields)
        sess.add(d)
        await sess.commit()
        return d.id


# ─── who gets a board ──────────────────────────────────────────────────────

class TestShouldWorkDay:
    @pytest.mark.parametrize("agent_type", ["closer", "manager", "data_analyst", "orchestrator", "custom"])
    def test_proactive_types_work_a_board(self, agent_type):
        from aios.core.workday import should_work_day

        assert should_work_day(Agent(agent_type=agent_type, status="active"))

    @pytest.mark.parametrize("agent_type", ["sdr", "support"])
    def test_reactive_types_are_left_alone(self, agent_type):
        """SDR and support act when a message arrives. Putting them on a daily
        queue would have them prospecting leads that already have a live
        conversation open."""
        from aios.core.workday import should_work_day

        assert not should_work_day(Agent(agent_type=agent_type, status="active"))

    def test_draft_agents_do_not_clock_in(self):
        from aios.core.workday import should_work_day

        assert not should_work_day(Agent(agent_type="closer", status="draft"))

    def test_opt_out_is_honoured(self):
        from aios.core.workday import should_work_day

        assert not should_work_day(Agent(agent_type="closer", status="active", extra_data={"workday": False}))
        assert should_work_day(Agent(agent_type="closer", status="active", extra_data={"workday": True}))


# ─── the board itself ──────────────────────────────────────────────────────

async def test_board_holds_only_my_open_deals(test_session):
    """An agent working someone else's pipeline is a tenant/logic bug, and a
    closed deal is not work."""
    org = await _org("wd-scope")
    me = await _agent(org, " closer")
    other = await _agent(org, "other closer")
    mine = await _deal(org, me, lead_name="Mine")
    await _deal(org, other, lead_name="Theirs")
    await _deal(org, me, lead_name="Already won", stage="closed_won")

    from aios.db.engine import async_session
    from aios.core.workday import board_for_agent

    async with async_session() as sess:
        agent = await sess.get(Agent, me)
        board = await board_for_agent(agent, sess)

    assert [i["lead"] for i in board["items"]] == ["Mine"]
    assert board["items"][0]["deal_id"] == mine
    assert board["count"] == 1


async def test_overdue_follow_up_is_lifted_above_a_hotter_deal(test_session):
    """A rep who promised to call back today outranks a lead that merely scores
    higher. Sorting purely by timing is how a promise gets missed."""
    org = await _org("wd-overdue")
    me = await _agent(org, "closer")

    stale = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    await _deal(org, me, lead_name="Owed a call", source="lista_fria",
                extra_data={"next_follow_up": stale, "next_follow_up_note": "prometeu ligar"})
    await _deal(org, me, lead_name="Hot lead", source="form",
                extra_data={"attempts": 0})

    from aios.db.engine import async_session
    from aios.core.workday import board_for_agent

    async with async_session() as sess:
        board = await board_for_agent(await sess.get(Agent, me), sess)

    assert board["items"][0]["lead"] == "Owed a call"
    assert board["overdue"] == 1
    assert board["items"][0]["follow_up_note"] == "prometeu ligar"


async def test_future_follow_up_is_not_overdue(test_session):
    org = await _org("wd-future")
    me = await _agent(org, "closer")
    later = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    await _deal(org, me, extra_data={"next_follow_up": later})

    from aios.db.engine import async_session
    from aios.core.workday import board_for_agent

    async with async_session() as sess:
        board = await board_for_agent(await sess.get(Agent, me), sess)

    assert board["overdue"] == 0


async def test_garbage_timestamp_does_not_crash_the_board(test_session):
    org = await _org("wd-junk")
    me = await _agent(org, "closer")
    await _deal(org, me, extra_data={"next_follow_up": "not-a-date"})

    from aios.db.engine import async_session
    from aios.core.workday import board_for_agent

    async with async_session() as sess:
        board = await board_for_agent(await sess.get(Agent, me), sess)

    assert board["count"] == 1
    assert board["overdue"] == 0


async def test_empty_board_renders_to_nothing():
    """No deals must produce no agent run at all. An empty prompt would burn a
    model call every morning to be told there is nothing to do."""
    from aios.core.workday import render_board

    assert render_board({"date": "2026-10-03", "count": 0, "overdue": 0, "items": []}) == ""


def test_render_board_names_the_deals_and_the_rules():
    from aios.core.workday import render_board

    out = render_board(
        {
            "date": "2026-10-03",
            "count": 1,
            "overdue": 1,
            "items": [
                {
                    "deal_id": "d1", "lead": "Ana", "stage": "sql", "value": 5000.0,
                    "timing": 60, "why": [], "hours_since_touch": 72.0,
                    "next_follow_up": "", "follow_up_note": "reenviar proposta",
                    "due_overdue": "2026-10-01T09:00:00+00:00", "summary": "quer orçamento",
                }
            ],
        }
    )
    assert "d1" in out and "Ana" in out
    assert "VENCIDO" in out
    assert "reenviar proposta" in out
    assert "quer orçamento" in out


# ─── SDR -> CRM handoff ────────────────────────────────────────────────────

async def test_inbound_creates_a_deal_so_the_next_agent_has_a_record(test_session):
    from aios.db.engine import async_session
    from aios.core.crm_handoff import ensure_deal_for_contact

    org = await _org("h-create")
    async with async_session() as sess:
        deal_id = await ensure_deal_for_contact(sess, org_id=org, phone="+55 (11) 99999-8888", name="Joana")
        await sess.commit()

    assert deal_id
    async with async_session() as sess:
        deal = await sess.get(CrmDeal, deal_id)
        assert deal.lead_phone == "+55 (11) 99999-8888"
        assert deal.lead_name == "Joana"
        assert deal.stage == "prospection"


async def test_second_message_reuses_the_same_deal(test_session):
    """Matching is by phone digits. Without it a chatty lead accumulated one
    deal per message and the Closer had no single row to inherit."""
    from aios.db.engine import async_session
    from aios.core.crm_handoff import ensure_deal_for_contact
    from sqlalchemy import select

    org = await _org("h-same")
    async with async_session() as sess:
        first = await ensure_deal_for_contact(sess, org_id=org, phone="+5511999998888")
        await sess.commit()
    async with async_session() as sess:
        second = await ensure_deal_for_contact(sess, org_id=org, phone="55 11 99999 8888")
        await sess.commit()

    assert first == second
    async with async_session() as sess:
        rows = (await sess.execute(select(CrmDeal).where(CrmDeal.org_id == org))).scalars().all()
    assert len(rows) == 1


async def test_no_phone_creates_nothing(test_session):
    """Unmatched every time, so a fresh row per message would be worse than not
    recording it."""
    from aios.db.engine import async_session
    from aios.core.crm_handoff import ensure_deal_for_contact
    from sqlalchemy import select

    org = await _org("h-nophone")
    async with async_session() as sess:
        assert await ensure_deal_for_contact(sess, org_id=org, phone=None) is None
    async with async_session() as sess:
        rows = (await sess.execute(select(CrmDeal).where(CrmDeal.org_id == org))).scalars().all()
    assert rows == []


async def test_recorded_conversation_is_readable_by_the_next_agent(test_session):
    """The point of the handoff: what was said outlives the SDR's context."""
    from aios.db.engine import async_session
    from aios.core.crm_handoff import ensure_deal_for_contact, record_interaction

    org = await _org("h-record")
    rep = await _agent(org, "sdr-bot", agent_type="sdr")

    async with async_session() as sess:
        deal_id = await ensure_deal_for_contact(sess, org_id=org, phone="+5511888887777", name="Rui")
        await record_interaction(
            sess, deal_id, org, rep,
            inbound_text="quero saber o preço do plano Pro",
            reply_text="Enviei a tabela por aqui, São R$ 490/mês.",
        )
        await sess.commit()

    async with async_session() as sess:
        deal = await sess.get(CrmDeal, deal_id)
        assert "R$ 490" in deal.extra_data["last_summary"]
        assert deal.extra_data["last_contacted_at"]
        assert len(deal.extra_data["sdr_history"]) == 1
        versions = (await sess.execute(
            select(CrmDealVersion).where(CrmDealVersion.deal_id == deal_id)
        )).scalars().all()
        assert len(versions) == 1
        assert versions[0].changed_by == rep
        assert "plano Pro" in versions[0].new_value


async def test_history_keeps_the_tail_not_the_head(test_session):
    """A long conversation must not grow without bound, and the recent
    exchanges are the ones the next agent needs."""
    from aios.db.engine import async_session
    from aios.core.crm_handoff import ensure_deal_for_contact, record_interaction

    org = await _org("h-tail")
    async with async_session() as sess:
        deal_id = await ensure_deal_for_contact(sess, org_id=org, phone="+5511000000001")
        for i in range(14):
            await record_interaction(sess, deal_id, org, None, f"msg {i}", f"reply {i}")
        await sess.commit()

    async with async_session() as sess:
        deal = await sess.get(CrmDeal, deal_id)
        history = deal.extra_data["sdr_history"]
        assert len(history) == 10
        assert history[-1]["summary"].endswith("reply 13")


async def test_handoff_never_crosses_tenants(test_session):
    from aios.db.engine import async_session
    from aios.core.crm_handoff import ensure_deal_for_contact

    org_a = await _org("h-a")
    org_b = await _org("h-b")
    async with async_session() as sess:
        await ensure_deal_for_contact(sess, org_id=org_a, phone="+5511999990000")
        await sess.commit()

    async with async_session() as sess:
        other = await ensure_deal_for_contact(sess, org_id=org_b, phone="+5511999990000")
        await sess.commit()

    async with async_session() as sess:
        a_deal = (await sess.execute(select(CrmDeal).where(CrmDeal.org_id == org_a))).scalars().all()
        b_deal = (await sess.execute(select(CrmDeal).where(CrmDeal.id == other))).scalars().all()
    # Same phone, different tenant: a distinct deal, and A's is untouched.
    assert len(a_deal) == 1
    assert len(b_deal) == 1
    assert a_deal[0].id != other


# ─── the job clocks the right agents in ────────────────────────────────────

async def test_workday_job_skips_reactive_and_empty_agents(test_session, monkeypatch):
    """No board means no run. An agent must never be woken to be told there is
    nothing to do."""
    from aios.tasks import jobs as J

    org = await _org("job-skip")
    await _enable_workday(org)
    closer = await _agent(org, "closer-bot")            # no deals -> empty board
    await _deal(org, closer, lead_name="owned by closer")

    ran: list[str] = []

    class _FakeAuto:
        def __init__(self, agent):
            self.agent = agent

        async def run(self, conv, msg, db=None, emit=None):
            ran.append(self.agent.id)
            return "worked"

    monkeypatch.setattr("aios.core.autonomous_agent.AutonomousAgent", _FakeAuto)
    monkeypatch.setattr("aios.core.events.publish", _noop_publish)

    result = await J.workday_job(None)
    assert result["worked"] == 1
    assert result["empty"] == 0
    assert ran == [closer]


async def _noop_publish(*a, **k):
    return None


async def test_workday_job_ignores_sdr_and_support(test_session, monkeypatch):
    from aios.tasks import jobs as J

    org = await _org("job-reactive")
    await _enable_workday(org)
    sdr = await _agent(org, "sdr-bot", agent_type="sdr")
    support = await _agent(org, "support-bot", agent_type="support")
    # Give them deals: if the filter were wrong they would clock in and run.
    await _deal(org, sdr, lead_name="sdr deal")
    await _deal(org, support, lead_name="support deal")

    ran: list[str] = []

    class _FakeAuto:
        def __init__(self, agent):
            self.agent = agent

        async def run(self, conv, msg, db=None, emit=None):
            ran.append(self.agent.id)
            return "x"

    monkeypatch.setattr("aios.core.autonomous_agent.AutonomousAgent", _FakeAuto)
    monkeypatch.setattr("aios.core.events.publish", _noop_publish)

    result = await J.workday_job(None)
    assert ran == []
    assert result["worked"] == 0


# ─── the master switch ─────────────────────────────────────────────────────

class TestOrgSwitch:
    def test_off_by_default(self):
        """Shipping this must not start every agent working. An operator turns
        it on deliberately."""
        from aios.core.workday import org_workday_enabled

        assert not org_workday_enabled(Organization(name="x", slug="x"))
        assert not org_workday_enabled(Organization(extra_data={}))
        assert not org_workday_enabled(Organization(extra_data={"workday_enabled": False}))
        assert not org_workday_enabled(None)

    def test_a_real_true_enables(self):
        from aios.core.workday import org_workday_enabled

        assert org_workday_enabled(Organization(extra_data={"workday_enabled": True}))

    def test_junk_is_not_truthy(self):
        """`is True`, so a string or a number from a hand-edited row cannot
        quietly start spending tokens."""
        from aios.core.workday import org_workday_enabled

        # Strings and numbers included on purpose: the dashboard and the API both
        # write a real bool, so anything else means a hand-edited row and must
        # not start an org spending tokens.
        for junk in ("true", "1", "sim", "yes", 1, "on", [1]):
            assert not org_workday_enabled(Organization(extra_data={"workday_enabled": junk}))


async def test_job_does_nothing_while_the_org_is_off(test_session, monkeypatch):
    """The switch has to actually stop the work, not just display a state."""
    from aios.tasks import jobs as J

    org = await _org("off-switch")
    closer = await _agent(org, "closer-bot")
    await _deal(org, closer, lead_name="has work")

    ran: list[str] = []

    class _FakeAuto:
        def __init__(self, agent):
            self.agent = agent

        async def run(self, conv, msg, db=None, emit=None):
            ran.append(self.agent.id)
            return "x"

    monkeypatch.setattr("aios.core.autonomous_agent.AutonomousAgent", _FakeAuto)
    monkeypatch.setattr("aios.core.events.publish", _noop_publish)

    result = await J.workday_job(None)
    assert ran == [], "an agent worked its board with the org switch off"
    assert result["worked"] == 0
    assert result["orgs_paused"] == 1


async def test_job_works_once_the_org_is_switched_on(test_session, monkeypatch):
    from aios.db.engine import async_session
    from aios.tasks import jobs as J

    org = await _org("on-switch")
    closer = await _agent(org, "closer-bot")
    await _deal(org, closer, lead_name="has work")

    async with async_session() as sess:
        o = await sess.get(Organization, org)
        o.extra_data = {"workday_enabled": True}
        await sess.commit()

    ran: list[str] = []

    class _FakeAuto:
        def __init__(self, agent):
            self.agent = agent

        async def run(self, conv, msg, db=None, emit=None):
            ran.append(self.agent.id)
            return "x"

    monkeypatch.setattr("aios.core.autonomous_agent.AutonomousAgent", _FakeAuto)
    monkeypatch.setattr("aios.core.events.publish", _noop_publish)

    result = await J.workday_job(None)
    assert ran == [closer]
    assert result["worked"] == 1
    assert result["orgs_paused"] == 0


async def test_a_paused_org_is_not_revived_by_an_agent_flag(test_session, monkeypatch):
    """The org switch is absolute. Otherwise pausing would not actually pause
    anything that had been configured before the pause."""
    from aios.tasks import jobs as J

    org = await _org("absolute")
    closer = await _agent(org, "eager-bot", workday=True)
    await _deal(org, closer, lead_name="has work")

    ran: list[str] = []

    class _FakeAuto:
        def __init__(self, agent):
            self.agent = agent

        async def run(self, conv, msg, db=None, emit=None):
            ran.append(self.agent.id)
            return "x"

    monkeypatch.setattr("aios.core.autonomous_agent.AutonomousAgent", _FakeAuto)
    monkeypatch.setattr("aios.core.events.publish", _noop_publish)

    result = await J.workday_job(None)
    assert ran == []
    assert result["worked"] == 0


async def test_toggle_endpoint_flips_the_switch(test_org, async_client, test_user, auth_headers):
    """The switch has to be operable, not just readable.

    Uses the `test_org` fixture rather than a fresh org: `async_client` is bound
    to it, so a switch written against another org would never be visible here.
    """
    async with _cookie(async_client, test_user):
        r = await async_client.get("/api/agents/workday/status", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["enabled"] is False

        r = await async_client.post(
            "/api/agents/workday/toggle", json={"enabled": True}, headers=auth_headers
        )
        assert r.status_code == 200, r.text
        assert r.json()["enabled"] is True

        async with async_session() as sess:
            o = await sess.get(Organization, test_org.id)
            assert o.extra_data["workday_enabled"] is True

        r = await async_client.get("/api/agents/workday/status", headers=auth_headers)
        assert r.json()["enabled"] is True

        r = await async_client.post(
            "/api/agents/workday/toggle", json={"enabled": False}, headers=auth_headers
        )
        assert r.json()["enabled"] is False


async def test_status_reports_what_the_switch_would_actually_do(
    test_org, test_session, async_client, test_user, auth_headers
):
    """Zero eligible agents with the switch on looks like it worked and does
    nothing, so the count has to be reported."""
    closer = await _agent(test_org.id, "closer-count")
    await _deal(test_org.id, closer, lead_name="owned")

    async with _cookie(async_client, test_user):
        # Flipped through the API rather than written from another session: the
        # client runs on a session opened before this test, so a cross-session
        # write can read back stale.
        r = await async_client.post(
            "/api/agents/workday/toggle", json={"enabled": True}, headers=auth_headers
        )
        assert r.status_code == 200, r.text
        r = await async_client.get("/api/agents/workday/status", headers=auth_headers)
    body = r.json()
    assert body["enabled"] is True
    assert body["eligible_agents"] == 1
    assert body["open_deals_owned"] == 1


async def test_settings_page_shows_the_switch(async_client, test_user):
    """The switch has to be reachable without calling the API by hand."""
    async with _cookie(async_client, test_user):
        r = await async_client.get("/dashboard/settings")
    assert r.status_code == 200, r.text
    assert 'id="workday-toggle"' in r.text
    assert "/dashboard/settings/workday" in r.text


async def test_settings_switch_writes_the_flag(test_org, async_client, test_user):
    async with _cookie(async_client, test_user):
        r = await async_client.post(
            "/dashboard/settings/workday", data={"enabled": "1"}, headers={"Referer": "http://test/dashboard/settings"}
        )
        assert r.status_code in (200, 303), r.text

        r = await async_client.post(
            "/dashboard/settings/workday", data={"enabled": "0"}, headers={"Referer": "http://test/dashboard/settings"}
        )
        assert r.status_code in (200, 303), r.text

        r = await async_client.get("/dashboard/settings")
        assert "Pausada" in r.text


async def test_settings_switch_is_not_reachable_cross_origin(test_org, async_client, test_user):
    """The toggle is a state change, so the dashboard's Referer check has to
    cover it. Without this a third-party page could pause every agent in the
    org with one cross-origin form post."""
    async with _cookie(async_client, test_user):
        r = await async_client.post(
            "/dashboard/settings/workday",
            data={"enabled": "1"},
            headers={"Referer": "https://evil.example.com/attack"},
        )
        assert r.status_code == 403, r.text
