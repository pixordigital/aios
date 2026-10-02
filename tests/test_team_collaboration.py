"""Manager-to-manager collaboration, owner notification, and goal reports.

Covers the three things the owner asked for:
1. a manager (or orchestrator) handing work to another team's manager and
   getting the reply back, cross-team but never cross-org;
2. a manager pushing a message to the owner's Slack on demand;
3. weekly/monthly reports that carry goal status and the manager's own
   remediation plan — and say so plainly when the manager stayed silent
   rather than inventing a plan.
"""

import pytest
from sqlalchemy import select

from aios.core.agent import is_failed_run
from aios.core.meetings import report_targets, report_text
from aios.db.models import (
    Agent,
    ChannelConnection,
    Conversation,
    Message,
    Organization,
    Team,
    team_agents,
)
from aios.tools.team_collaboration import (
    _MAX_HOPS,
    AskTeamManagerTool,
    NotifyHumanTool,
    _hops,
)

# ── fixtures ─────────────────────────────────────────────────────────────

async def _org(session, slug: str, plan: str = "unlimited") -> Organization:
    org = Organization(name=slug, slug=slug, extra_data={"plan": plan})
    session.add(org)
    await session.commit()
    await session.refresh(org)
    return org


async def _team(session, org, name: str) -> Team:
    team = Team(org_id=org.id, name=name, routing_strategy="supervisor")
    session.add(team)
    await session.commit()
    await session.refresh(team)
    return team


async def _agent(session, org, name: str) -> Agent:
    agent = Agent(
        org_id=org.id,
        name=name,
        agent_type="manager",
        system_prompt="prompt",
        tools=["ask_team_manager", "notify_human"],
        status="active",
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def _join(session, team, agent) -> None:
    await session.execute(team_agents.insert().values(team_id=team.id, agent_id=agent.id))
    await session.commit()


class _Conn:
    """Minimal ChannelConnection stand-in for report_targets()."""

    def __init__(self, team_id, channel, one_on_one=False, token="t"):
        self.id = f"c-{team_id}-{channel}"
        self.team_id = team_id
        self.config = {
            "slack_channel_id": channel,
            "bot_token": token,
            "slack_1on1": one_on_one,
        }


# ── 1. cross-team collaboration ──────────────────────────────────────────

async def test_ask_team_manager_reaches_other_team_and_returns_reply(test_session, monkeypatch):
    org = await _org(test_session, "collab-org")
    sales = await _team(test_session, org, "sales")
    dev = await _team(test_session, org, "dev")

    sales_mgr = await _agent(test_session, org, "sales-manager")
    dev_mgr = await _agent(test_session, org, "dev-manager")
    sales.manager_agent_id = sales_mgr.id
    dev.manager_agent_id = dev_mgr.id
    await _join(test_session, sales, sales_mgr)
    await _join(test_session, dev, dev_mgr)
    await test_session.commit()

    seen = {}

    class _Runtime:
        def __init__(self, agent, _db):
            self.agent = agent

        async def run(self, conv_id, prompt, db=None):
            seen["conv_id"] = conv_id
            seen["agent"] = self.agent
            seen["prompt"] = prompt
            return "consigo revisar amanha de manha"

    monkeypatch.setattr("aios.core.orchestrator._get_runtime", lambda a, db=None: _Runtime(a, db))

    tool = AskTeamManagerTool()
    tool._org_id = org.id
    tool._agent_id = sales_mgr.id
    out = await tool.run(to_team="dev", question="revisa a migration?")

    assert out["ok"] is True
    assert out["manager"] == "dev-manager"
    assert "amanha" in out["reply"]
    assert seen["agent"].id == dev_mgr.id
    assert "sales" in seen["prompt"]

    # The thread belongs to the *target* team and records the requester.
    conv = await test_session.get(Conversation, out["conversation_id"])
    assert conv.team_id == dev.id
    assert conv.agent_id == dev_mgr.id
    collab = conv.extra_data["collab"]
    assert collab["from_team_id"] == sales.id
    assert collab["to_team_id"] == dev.id

    msgs = (await test_session.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    )).scalars().all()
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[0].extra_data["from_team_id"] == sales.id
    assert msgs[1].agent_id == dev_mgr.id


async def test_ask_team_manager_reuses_thread_for_same_pair(test_session, monkeypatch):
    org = await _org(test_session, "collab-reuse")
    a = await _team(test_session, org, "alpha")
    b = await _team(test_session, org, "beta")
    a_mgr = await _agent(test_session, org, "alpha-manager")
    b_mgr = await _agent(test_session, org, "beta-manager")
    a.manager_agent_id, b.manager_agent_id = a_mgr.id, b_mgr.id
    await _join(test_session, a, a_mgr)
    await _join(test_session, b, b_mgr)
    await test_session.commit()

    class _Runtime:
        def __init__(self, agent, _db):
            pass

        async def run(self, conv_id, prompt, db=None):
            return "ok"

    monkeypatch.setattr("aios.core.orchestrator._get_runtime", lambda ag, db=None: _Runtime(ag, db))

    tool = AskTeamManagerTool()
    tool._org_id, tool._agent_id = org.id, a_mgr.id
    first = await tool.run(to_team="beta", question="1a")
    second = await tool.run(to_team="beta", question="2a")
    assert first["conversation_id"] == second["conversation_id"]

    convs = (await test_session.execute(
        select(Conversation).where(Conversation.external_id == f"collab:{a.id}->{b.id}")
    )).scalars().all()
    assert len(convs) == 1


async def test_ask_team_manager_refuses_cross_org(test_session, monkeypatch):
    """A team that exists only in another org must not be reachable."""
    mine = await _org(test_session, "org-mine")
    theirs = await _org(test_session, "org-theirs")
    team_mine = await _team(test_session, mine, "sales")
    # Only the other org has a team by this name.
    team_theirs = await _team(test_session, theirs, "forensics")
    mgr_mine = await _agent(test_session, mine, "mgr-mine")
    mgr_theirs = await _agent(test_session, theirs, "mgr-theirs")
    team_mine.manager_agent_id, team_theirs.manager_agent_id = mgr_mine.id, mgr_theirs.id
    await _join(test_session, team_mine, mgr_mine)
    await test_session.commit()

    ran = []
    monkeypatch.setattr(
        "aios.core.orchestrator._get_runtime",
        lambda a, db=None: ran.append(a.id) or None,
    )

    tool = AskTeamManagerTool()
    tool._org_id, tool._agent_id = mine.id, mgr_mine.id
    out = await tool.run(to_team="forensics", question="oi")

    assert out["ok"] is False
    assert "not found" in out["error"]
    # Their manager never ran, and no thread was created on either side.
    assert ran == []
    convs = (await test_session.execute(select(Conversation))).scalars().all()
    assert convs == []


async def test_ask_team_manager_refuses_own_team(test_session):
    org = await _org(test_session, "self-team")
    team = await _team(test_session, org, "sales")
    mgr = await _agent(test_session, org, "sales-manager")
    team.manager_agent_id = mgr.id
    await _join(test_session, team, mgr)
    await test_session.commit()

    tool = AskTeamManagerTool()
    tool._org_id, tool._agent_id = org.id, mgr.id
    out = await tool.run(to_team="sales", question="me ajuda")

    assert out["ok"] is False
    assert "your own team" in out["error"]


async def test_ask_team_manager_requires_resolved_org(test_session):
    tool = AskTeamManagerTool()
    assert tool._org_id == ""
    with pytest.raises(PermissionError):
        await tool.run(to_team="dev", question="oi")


async def test_ask_team_manager_hop_limit_stops_runaway_pingpong(test_session, monkeypatch):
    """Two managers bouncing the same question must terminate."""
    org = await _org(test_session, "hops")
    a = await _team(test_session, org, "alpha")
    b = await _team(test_session, org, "beta")
    a_mgr = await _agent(test_session, org, "alpha-manager")
    b_mgr = await _agent(test_session, org, "beta-manager")
    a.manager_agent_id, b.manager_agent_id = a_mgr.id, b_mgr.id
    await _join(test_session, a, a_mgr)
    await _join(test_session, b, b_mgr)
    await test_session.commit()

    # The target manager asks back, forever.
    class _PingPong:
        def __init__(self, agent, _db):
            pass

        async def run(self, conv_id, prompt, db=None):
            nested = AskTeamManagerTool()
            nested._org_id, nested._agent_id = org.id, b_mgr.id
            out = await nested.run(to_team="alpha", question="e voce?")
            return f"nested={out}"

    monkeypatch.setattr("aios.core.orchestrator._get_runtime", lambda ag, db=None: _PingPong(ag, db))

    tool = AskTeamManagerTool()
    tool._org_id, tool._agent_id = org.id, a_mgr.id
    token = _hops.set(0)
    try:
        out = await tool.run(to_team="beta", question="oi")
    finally:
        _hops.reset(token)

    # The innermost hop refused rather than recursing further.
    assert out["ok"] is True
    assert "hop limit reached" in out["reply"]
    assert _MAX_HOPS == 3


async def test_ask_team_manager_reports_manager_failure_without_claiming_success(
    test_session, monkeypatch
):
    org = await _org(test_session, "failmgr")
    a = await _team(test_session, org, "alpha")
    b = await _team(test_session, org, "beta")
    a_mgr = await _agent(test_session, org, "alpha-manager")
    b_mgr = await _agent(test_session, org, "beta-manager")
    a.manager_agent_id, b.manager_agent_id = a_mgr.id, b_mgr.id
    await _join(test_session, a, a_mgr)
    await _join(test_session, b, b_mgr)
    await test_session.commit()

    class _Boom:
        def __init__(self, agent, _db):
            pass

        async def run(self, conv_id, prompt, db=None):
            raise RuntimeError("provider down")

    monkeypatch.setattr("aios.core.orchestrator._get_runtime", lambda ag, db=None: _Boom(ag, db))

    tool = AskTeamManagerTool()
    tool._org_id, tool._agent_id = org.id, a_mgr.id
    out = await tool.run(to_team="beta", question="oi")

    assert out["ok"] is False
    assert "did not answer" in out["error"]
    # The request is still on the thread for a retry.
    msgs = (await test_session.execute(
        select(Message).where(Message.conversation_id == out["conversation_id"])
    )).scalars().all()
    assert len(msgs) == 1


# ── 2. manager notifies the owner ────────────────────────────────────────

async def test_notify_human_posts_to_owner_dm(test_session, monkeypatch):
    org = await _org(test_session, "notify")
    sales = await _team(test_session, org, "sales")
    mgr = await _agent(test_session, org, "sales-manager")
    sales.manager_agent_id = mgr.id
    await _join(test_session, sales, mgr)

    test_session.add(ChannelConnection(
        org_id=org.id, label="Slack #sales", channel_type="slack", team_id=sales.id,
        config={"bot_token": "xoxb", "slack_channel_id": "C_TEAM"}, is_active=True,
    ))
    test_session.add(ChannelConnection(
        org_id=org.id, label="Slack 1:1 sales", channel_type="slack", team_id=sales.id,
        config={"bot_token": "xoxb", "slack_channel_id": "D_OWNER", "slack_1on1": True},
        is_active=True,
    ))
    await test_session.commit()

    posted = []
    monkeypatch.setattr(
        "aios.core.meetings.post_to_slack",
        lambda token, channel, text: posted.append((channel, text)) or True,
    )

    tool = NotifyHumanTool()
    tool._org_id, tool._agent_id = org.id, mgr.id
    # No `team` argument: it resolves the caller's own team.
    out = await tool.run(message="meta de vendas quebrou", urgency="warning")

    assert out["ok"] is True
    assert out["channels"] == ["D_OWNER"]
    channel, text = posted[0]
    assert channel == "D_OWNER"
    assert "WARNING" in text and "meta de vendas quebrou" in text and "sales" in text


async def test_notify_human_refuses_team_room_for_urgent_message(test_session, monkeypatch):
    """No DM wired -> say so, don't dump an urgent message in the team room."""
    org = await _org(test_session, "notify-nodm")
    sales = await _team(test_session, org, "sales")
    test_session.add(ChannelConnection(
        org_id=org.id, label="Slack #sales", channel_type="slack", team_id=sales.id,
        config={"bot_token": "xoxb", "slack_channel_id": "C_TEAM"}, is_active=True,
    ))
    await test_session.commit()

    posted = []
    monkeypatch.setattr(
        "aios.core.meetings.post_to_slack",
        lambda token, channel, text: posted.append(channel) or True,
    )

    tool = NotifyHumanTool()
    tool._org_id = org.id
    out = await tool.run(message="oi", team="sales")

    assert out["ok"] is False
    assert "slack_1on1" in out["error"]
    assert posted == []


async def test_notify_human_never_crosses_org(test_session, monkeypatch):
    mine = await _org(test_session, "mine")
    theirs = await _org(test_session, "theirs")
    test_session.add(ChannelConnection(
        org_id=theirs.id, label="1on1", channel_type="slack",
        config={"bot_token": "x", "slack_channel_id": "D_THEIRS", "slack_1on1": True},
        is_active=True,
    ))
    await test_session.commit()

    posted = []
    monkeypatch.setattr(
        "aios.core.meetings.post_to_slack",
        lambda token, channel, text: posted.append(channel) or True,
    )

    tool = NotifyHumanTool()
    tool._org_id = mine.id
    await tool.run(message="oi")
    assert posted == []


async def test_ask_team_manager_does_not_report_empty_reply_as_success(test_session, monkeypatch):
    """AgentRuntime returns a canned apology instead of raising on provider failure."""
    org = await _org(test_session, "canned")
    a = await _team(test_session, org, "alpha")
    b = await _team(test_session, org, "beta")
    a_mgr = await _agent(test_session, org, "alpha-manager")
    b_mgr = await _agent(test_session, org, "beta-manager")
    a.manager_agent_id, b.manager_agent_id = a_mgr.id, b_mgr.id
    await _join(test_session, a, a_mgr)
    await _join(test_session, b, b_mgr)
    await test_session.commit()

    class _Canned:
        def __init__(self, agent, _db):
            pass

        async def run(self, conv_id, prompt, db=None):
            return "I'm having trouble completing this request. Please try again."

    monkeypatch.setattr("aios.core.orchestrator._get_runtime", lambda ag, db=None: _Canned(ag, db))

    tool = AskTeamManagerTool()
    tool._org_id, tool._agent_id = org.id, a_mgr.id
    out = await tool.run(to_team="beta", question="oi")

    assert out["ok"] is False
    assert "could not answer" in out["error"]
    msgs = (await test_session.execute(
        select(Message).where(Message.conversation_id == out["conversation_id"])
    )).scalars().all()
    # Request kept, no fake answer written.
    assert [m.role for m in msgs] == ["user"]


async def test_notify_human_survives_null_optional_args(test_session, monkeypatch):
    """ToolEngine forwards LLM args unvalidated; null optionals must not crash."""
    org = await _org(test_session, "nulls")
    sales = await _team(test_session, org, "sales")
    test_session.add(ChannelConnection(
        org_id=org.id, label="1on1", channel_type="slack", team_id=sales.id,
        config={"bot_token": "x", "slack_channel_id": "D_OWNER", "slack_1on1": True},
        is_active=True,
    ))
    await test_session.commit()

    posted = []
    monkeypatch.setattr(
        "aios.core.meetings.post_to_slack",
        lambda token, channel, text: posted.append(text) or True,
    )

    tool = NotifyHumanTool()
    tool._org_id = org.id
    out = await tool.run(message="preciso de decisao", urgency=None, team=None)

    assert out["ok"] is True
    assert "INFO" in posted[0] and "preciso de decisao" in posted[0]


# ── 3. weekly/monthly reports ────────────────────────────────────────────

_GOAL_BEHIND = {
    "year_month": "2026-09", "target_brl": 10000.0, "won_brl": 2000.0,
    "deals_won": 1, "day": 20, "days_in_month": 30, "expected_brl": 6666.0,
    "pct": 20.0, "projected_brl": 3000.0, "remaining_brl": 8000.0, "status": "behind",
}


def test_report_targets_prefers_dm_then_falls_back_to_team_channel():
    assert [t["channel"] for t in report_targets(
        [_Conn("t1", "C_ROOM"), _Conn("t1", "D_DM", one_on_one=True)], "t1"
    )] == ["D_DM"]

    assert [t["channel"] for t in report_targets([_Conn("t1", "C_ROOM")], "t1")] == ["C_ROOM"]

    # Another team's DM is not this team's report destination.
    assert report_targets([_Conn("t2", "D_OTHER", one_on_one=True)], "t1") == []


def test_report_targets_ignores_connection_missing_token_or_channel():
    broken = _Conn("t1", "C_ROOM")
    broken.config = {"bot_token": "", "slack_channel_id": "C_ROOM"}
    assert report_targets([broken], "t1") == []


def test_report_text_carries_goal_and_manager_recovery_plan():
    stats = {"days": 7, "conversations": 12, "messages": 88, "won_brl": 2000.0}
    text = report_text(
        "weekly", "vendas", "ana", stats, _GOAL_BEHIND,
        "Time parou de prospectar. Vou dobrar a coercao ate sexta eumpesso com o closer.",
    )
    assert "Relatorio Semanal" in text and "vendas" in text
    assert "R$2000.00 de R$10000.00" in text
    assert "atrasado" in text
    # The recovery plan is the manager's own words.
    assert "ate sexta" in text
    assert "plano de recuperacao" in text
    # The weekly post doubles as the 1:1 agenda.
    assert "Pauta da nossa 1:1" in text


def test_report_text_says_so_when_manager_stayed_silent():
    """No manager answer must not read as 'there is no problem'."""
    stats = {"days": 7, "conversations": 3, "messages": 9, "won_brl": 0.0}
    text = report_text("weekly", "vendas", "ana", stats, _GOAL_BEHIND, "")
    assert "gerente nao respondeu" in text
    assert "plano de acao nao foi reportado" in text


# ── a failed agent run must never reach the owner ────────────────────────

@pytest.mark.parametrize(
    "failed",
    [
        "I'm having trouble completing this request. Please try again.",
        "Não consegui resolver. Tente reformular.",
        "Falha: Ineficiente: não chamou tool. Tentar abordagem diferente.",
        "⏸️ [HITL] Não consegui resolver autonomamente após 3 tentativas.",
        "Falha após 3 tentativas autônomas",
        "",
        "   ",
    ],
)
def test_is_failed_run_flags_every_runtime_failure_notice(failed):
    assert is_failed_run(failed) is True


def test_is_failed_run_passes_real_answers_through():
    """A report that merely mentions 'não consegui' about a lead is not a failure."""
    real = "O closer não conseguiu falar com o decisor do Pixor; vou tentar na terça."
    assert is_failed_run(real) is False


def test_agent_orchestrator_import_cycle_resolves_either_way():
    """Regression: is_failed_run must survive a half-initialised agent module.

    orchestrator imports it at module level and the two modules import each
    other, so the definition has to sit above AgentRuntime. When it sat below
    the class, whichever module was imported first decided whether the process
    started at all — and it only failed for some test-file orderings.
    """
    import subprocess
    import sys

    for first in ("aios.core.agent", "aios.core.orchestrator"):
        proc = subprocess.run(
            [sys.executable, "-c", f"import {first}; import aios.core.orchestrator"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"{first} first: {proc.stderr[-400:]}"


async def test_manager_narrative_drops_failed_run(test_session, monkeypatch):
    """A failed evaluation loop must not be published as the team's report."""
    from aios.core.meetings import manager_narrative

    org = await _org(test_session, "narrative-fail")
    team = await _team(test_session, org, "vendas")
    mgr = await _agent(test_session, org, "vendas-manager")
    team.manager_agent_id = mgr.id
    await test_session.commit()

    class _Failed:
        def __init__(self, agent, _db):
            pass

        async def run(self, conv_id, prompt, db=None):
            return "Falha: Ineficiente: não chamou tool. Tentar abordagem diferente."

    monkeypatch.setattr("aios.core.orchestrator._get_runtime", lambda a, db=None: _Failed(a, db))

    stats = {"days": 7, "conversations": 1, "messages": 2, "won_brl": 0.0}
    assert await manager_narrative(mgr, team, stats, _GOAL_BEHIND, "weekly") == ""

    # Nothing fake was written to the report thread.
    from aios.db.models import Message as _M
    msgs = (await test_session.execute(select(_M))).scalars().all()
    assert msgs == []


def test_monthly_report_uses_previous_month_and_no_1on1_agenda():
    stats = {"days": 30, "conversations": 40, "messages": 300, "won_brl": 9000.0}
    goal = dict(_GOAL_BEHIND, year_month="2026-08", status="ahead", pct=90.0)
    text = report_text("monthly", "vendas", "ana", stats, goal, "Fechamos o mes.")
    assert "Relatorio Mensal" in text
    assert "Meta 2026-08" in text
    assert "mes fechado" in text
    # The agenda question list is for the weekly 1:1, not the monthly close.
    assert "Pauta da nossa 1:1" not in text


def test_report_text_without_goal_does_not_invent_one():
    stats = {"days": 7, "conversations": 1, "messages": 2, "won_brl": 0.0}
    text = report_text("weekly", "red", "bo", stats, None, "Tudo certo.")
    assert "sem meta cadastrada" in text
    assert "Meta atrasada" not in text


# ── the scheduled jobs actually run ──────────────────────────────────────

async def _wire_report_team(session, org, team_name, with_dm=True):
    team = await _team(session, org, team_name)
    mgr = await _agent(session, org, f"{team_name}-manager")
    team.manager_agent_id = mgr.id
    await _join(session, team, mgr)
    conns = []
    if with_dm:
        conns.append(ChannelConnection(
            org_id=org.id, label=f"1on1 {team_name}", channel_type="slack", team_id=team.id,
            config={"bot_token": "xoxb", "slack_channel_id": f"D_{team_name}", "slack_1on1": True},
            is_active=True,
        ))
    for c in conns:
        session.add(c)
    await session.commit()
    return team, mgr


async def test_post_team_reports_delivers_to_owner_dm(test_session, monkeypatch):
    """The job body, not just the text builder.

    This is the test that catches a missing import in the job: the first real
    run of this cron would otherwise NameError before posting anything.
    """
    from aios.tasks.jobs import _post_team_reports

    org = await _org(test_session, "report-job")
    await _wire_report_team(test_session, org, "vendas")

    posted = []

    async def _narrative(manager, t, stats, goal, kind):
        return "Time em dia, mantenho o ritmo."

    monkeypatch.setattr(
        "aios.core.meetings.manager_narrative", _narrative
    )
    monkeypatch.setattr(
        "aios.core.meetings.post_to_slack",
        lambda token, channel, text: posted.append((channel, text)) or True,
    )

    out = await _post_team_reports("weekly")

    assert out["posted"] == 1
    assert out["failed"] == 0
    assert out["teams_without_manager"] == 0
    channel, text = posted[0]
    assert channel == "D_vendas"
    assert "Relatorio Semanal" in text
    assert "mantenho o ritmo" in text


async def test_post_team_reports_counts_team_without_manager(test_session, monkeypatch):
    """A team with no manager is reported as a gap, not silently skipped."""
    from aios.tasks.jobs import _post_team_reports

    org = await _org(test_session, "report-nomgr")
    team = await _team(test_session, org, "orfaos")  # no manager_agent_id
    test_session.add(ChannelConnection(
        org_id=org.id, label="1on1 orfaos", channel_type="slack", team_id=team.id,
        config={"bot_token": "x", "slack_channel_id": "D_ORFAOS", "slack_1on1": True},
        is_active=True,
    ))
    await test_session.commit()

    posted = []
    monkeypatch.setattr(
        "aios.core.meetings.post_to_slack",
        lambda token, channel, text: posted.append(channel) or True,
    )

    out = await _post_team_reports("weekly")
    assert out["teams_without_manager"] == 1
    assert out["posted"] == 0
    assert posted == []


async def test_post_team_reports_still_delivers_when_manager_silent(test_session, monkeypatch):
    """Numbers go out even without a narrative — the gap is stated, not hidden."""
    from aios.tasks.jobs import _post_team_reports

    org = await _org(test_session, "report-silent")
    await _wire_report_team(test_session, org, "vendas")

    posted = []
    monkeypatch.setattr(
        "aios.core.meetings.manager_narrative",
        lambda *a, **k: _async_empty(),
    )
    monkeypatch.setattr(
        "aios.core.meetings.post_to_slack",
        lambda token, channel, text: posted.append(text) or True,
    )

    out = await _post_team_reports("weekly")
    assert out["posted"] == 1
    assert out["teams_manager_silent"] == 1
    assert "gerente nao respondeu" in posted[0]


async def _async_empty():
    return ""


async def test_report_jobs_skip_off_their_day(monkeypatch):
    """Both jobs self-skip, so a daily cron tick is a no-op 6 days a week."""
    import datetime as _dt

    from aios.tasks.jobs import monthly_report_job, weekly_report_job

    class _Tuesday(_dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 15)  # a Tuesday, and not the 1st

    monkeypatch.setattr(_dt, "date", _Tuesday)
    assert (await weekly_report_job(None))["skipped"] is True
    assert (await monthly_report_job(None))["skipped"] is True

    class _FirstOfMonth(_dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 1)

    monkeypatch.setattr(_dt, "date", _FirstOfMonth)
    assert (await weekly_report_job(None))["skipped"] is True  # 2026-09-01 is a Tuesday
    # Monthly proceeds past its gate and reaches the (empty) org list.
    assert "skipped" not in await monthly_report_job(None)