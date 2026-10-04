"""The cross-team build request: the owner is always told, or it does not happen.

`ask_team_manager` + `notify_human` could already express this in prompt text,
but prompt text is advice. Nothing stopped a sales manager from quietly asking
dev and never mentioning it. These tests pin the guarantees that replaced it:

- a justification with no figure is refused before anyone is contacted;
- a Slack failure means the request fails rather than proceeding unannounced;
- an empty feasibility analysis is not shipped to the owner as if it were an
  answer.
"""

import pytest

from aios.db.models import Agent, CrmDeal, Organization, PendingAction, Team, team_agents


async def _org() -> str:
    from aios.db.engine import async_session

    async with async_session() as sess:
        o = Organization(name="br-req", slug="br-req")
        sess.add(o)
        await sess.commit()
        return o.id


async def _agent(org_id: str, name: str, agent_type: str = "manager"):
    from aios.db.engine import async_session

    async with async_session() as sess:
        a = Agent(org_id=org_id, name=name, agent_type=agent_type, status="active")
        sess.add(a)
        await sess.commit()
        return a.id


async def _team(org_id: str, name: str, manager_id: str, member_id: str):
    from aios.db.engine import async_session

    async with async_session() as sess:
        t = Team(org_id=org_id, name=name, routing_strategy="hierarchical",
                 manager_agent_id=manager_id, orchestrator_agent_id=member_id)
        sess.add(t)
        await sess.flush()
        for pri, aid in enumerate([member_id, manager_id]):
            await sess.execute(team_agents.insert().values(team_id=t.id, agent_id=aid, priority=pri))
        await sess.commit()
        return t.id


async def _deal(org_id: str, agent_id: str, **kw):
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


@pytest.fixture
async def wired(test_session):
    """Sales and Dev teams, each with a manager, plus a patched runtime."""
    from aios.db.engine import async_session

    org = await _org()
    sales_mgr = await _agent(org, "Sales Manager")
    dev_mgr = await _agent(org, "Dev Manager")
    sales_rep = await _agent(org, "Closer", agent_type="closer")
    dev_rep = await _agent(org, "Backend", agent_type="backend")
    await _team(org, "Vendas", sales_mgr, sales_rep)
    await _team(org, "Dev", dev_mgr, dev_rep)

    async with async_session() as sess:
        caller = await sess.get(Agent, sales_mgr)

    posted: list[dict] = []

    class _RT:
        def __init__(self, agent, _db):
            self.agent = agent

        async def run(self, conv_id, prompt):
            return (
                "Dá para fazer. Escopo: um endpoint de checkout e um webhook. "
                "Esforço 3 dias. Risco baixo. Não vai resolver o abandono no mobile."
            )

    async def fake_post(text, targets):
        posted.append({"text": text, "targets": targets})
        return True

    async def no_targets(org_id, team_id=""):
        return ["U0OWNER"]

    import aios.core.orchestrator as orch

    orch._get_runtime = lambda agent, db: _RT(agent, db)

    import aios.core.meetings as meetings

    meetings.post_to_slack = fake_post
    meetings.human_slack_targets = no_targets

    class _Tool:
        """Same class, org/agent injected the way ToolEngine does."""
        from aios.tools.team_collaboration import RequestBuildTool as _R

        def __new__(cls):
            return cls._R()

    tool = _Tool()
    tool._org_id = org
    tool._agent_id = sales_mgr
    return {"tool": tool, "posted": posted, "org": org, "caller_id": caller.id}


# ─── the justification must be a fact, not a wish ──────────────────────────

class TestJustificationGate:
    async def test_refuses_without_any_evidence(self, wired):
        """Fails closed BEFORE contacting anyone, so the owner is never asked to
        rule on 'this would help sales'."""
        out = await wired["tool"].run(
            requirement="integrar checkout",
            revenue_justification="isso ajudaria a vender mais",
        )
        assert out["ok"] is False
        assert "no figure" in out["error"]
        assert wired["posted"] == [], "the owner was contacted without evidence"

    async def test_refuses_a_wish_that_only_names_a_team(self, wired):
        out = await wired["tool"].run(
            requirement="integrar checkout",
            revenue_justification="o time de vendas pediu",
        )
        assert out["ok"] is False
        assert wired["posted"] == []

    @pytest.mark.parametrize(
        "justification",
        [
            "R$ 40k de pipeline parado depende disso",
            "conversão está em 2%, queremos 4%",
            "agendamento caiu 30% no trimestre",
            "o churn de 8% mensal custa R$ 12k",
        ],
    )
    async def test_accepts_a_real_claim(self, wired, justification):
        out = await wired["tool"].run(
            requirement="integrar checkout", revenue_justification=justification
        )
        assert out["ok"] is True, out

    async def test_evidence_alone_does_not_substitute_for_the_claim(self, wired):
        """The justification is the argument; evidence only supports it."""
        out = await wired["tool"].run(
            requirement="integrar checkout",
            revenue_justification="melhoraria as vendas",
            evidence="relatório de junho",
        )
        assert out["ok"] is False
        assert wired["posted"] == []


# ─── the owner always hears both sides ─────────────────────────────────────

class TestOwnerIsAlwaysTold:
    async def test_message_carries_all_three_parts(self, wired):
        out = await wired["tool"].run(
            requirement="integrar checkout com Pix",
            revenue_justification="R$ 40k de pipeline parado depende disso",
            evidence="funil de junho",
        )
        assert out["ok"] is True, out
        assert len(wired["posted"]) == 1

        text = wired["posted"][0]["text"]
        assert "integrar checkout com Pix" in text          # what sales asked for
        assert "Análise de viabilidade" in text             # dev's answer
        assert "Endpoint de checkout" in text or "Escopo" in text
        assert "R$ 40k" in text                             # sales' justification
        assert "funil de junho" in text                    # cited evidence
        assert "Dev" in text and "Vendas" in text

    async def test_parks_an_approval_so_told_and_decided_are_distinct(self, wired):
        from aios.db.engine import async_session

        out = await wired["tool"].run(
            requirement="integrar checkout",
            revenue_justification="R$ 40k de pipeline parado",
        )
        assert out["ok"] is True
        assert out["owner_notified"] is True
        assert out["pending_approval_id"]

        async with async_session() as sess:
            pa = await sess.get(PendingAction, out["pending_approval_id"])
            assert pa.status == "pending"
            assert pa.tool_name == "request_build"
            # Tenant-scoped: an approval row with no org would leak into every
            # other tenant's queue.
            assert pa.org_id == wired["org"]
            assert pa.tool_args["revenue_justification"]

    async def test_thread_keeps_the_exchange(self, wired):
        from aios.db.engine import async_session
        from aios.db.models import Message
        from sqlalchemy import select

        out = await wired["tool"].run(
            requirement="integrar checkout",
            revenue_justification="R$ 40k de pipeline parado",
        )
        async with async_session() as sess:
            msgs = (
                await sess.execute(
                    select(Message).where(Message.conversation_id == out["conversation_id"])
                )
            ).scalars().all()
        directions = [m.extra_data.get("direction") for m in msgs if m.extra_data.get("collab")]
        assert "build_request" in directions
        assert "feasibility" in directions


# ─── fail closed when the owner cannot be reached ──────────────────────────

class TestFailsClosed:
    async def test_slack_failure_fails_the_request(self, wired):
        import aios.core.meetings as meetings

        async def dead(text, targets):
            return False

        meetings.post_to_slack = dead
        out = await wired["tool"].run(
            requirement="integrar checkout",
            revenue_justification="R$ 40k de pipeline parado",
        )
        assert out["ok"] is False
        assert "owner was NOT reached" in out["error"]

    async def test_slack_exception_fails_the_request(self, wired):
        import aios.core.meetings as meetings

        async def boom(text, targets):
            raise RuntimeError("slack down")

        meetings.post_to_slack = boom
        out = await wired["tool"].run(
            requirement="integrar checkout",
            revenue_justification="R$ 40k de pipeline parado",
        )
        assert out["ok"] is False
        assert "NOT delivered" in out["error"]

    async def test_no_slack_wired_means_not_delivered(self, wired):
        import aios.core.meetings as meetings

        async def nobody(org_id, team_id=""):
            return []

        meetings.human_slack_targets = nobody
        out = await wired["tool"].run(
            requirement="integrar checkout",
            revenue_justification="R$ 40k de pipeline parado",
        )
        assert out["ok"] is False
        assert "NOT delivered" in out["error"]

    async def test_empty_feasibility_is_not_shipped_to_the_owner(self, wired):
        """A failed manager run returns a canned apology, not an analysis. Sending
        that to the owner as 'here is the feasibility' would be a lie."""
        import aios.core.orchestrator as orch

        class _RT:
            def __init__(self, agent, _db):
                pass

            async def run(self, conv_id, prompt):
                # Exactly the marker the runtime emits; is_failed_run matches
                # case-sensitively, so a reworded apology would slip past it.
                return "Não consegui processar sua solicitação agora."

        orch._get_runtime = lambda agent, db: _RT(agent, db)

        out = await wired["tool"].run(
            requirement="integrar checkout",
            revenue_justification="R$ 40k de pipeline parado",
        )
        assert out["ok"] is False
        assert "NOT sent to the owner" in out["error"]
        assert wired["posted"] == []


# ─── it must not become a way around the owner ────────────────────────────

class TestNoSilentPath:
    async def test_asking_your_own_team_is_refused(self, wired):
        out = await wired["tool"].run(
            requirement="arrumar meu proprio pipeline",
            revenue_justification="R$ 10k",
            to_team="Vendas",
        )
        assert out["ok"] is False
        assert "your own team" in out["error"]
        assert wired["posted"] == []

    async def test_requires_a_resolved_org(self):
        from aios.tools.team_collaboration import RequestBuildTool

        tool = RequestBuildTool()
        tool._org_id = ""
        tool._agent_id = "a1"
        with pytest.raises(PermissionError):
            await tool.run(requirement="x", revenue_justification="R$ 1")

    async def test_registered_in_the_tool_registry(self):
        import aios.tools  # noqa: F401
        from aios.tools.registry import TOOL_REGISTRY

        assert "request_build" in TOOL_REGISTRY
        assert TOOL_REGISTRY["request_build"]["code_reference"].endswith("RequestBuildTool")


# ─── the rules cannot be walked around ─────────────────────────────────────

class TestNoBypass:
    """`request_build` is enforced, but a sales manager could still ask dev
    directly through ask_team_manager and never mention it. That is the same
    outcome the owner ruled out, reached one tool over."""

    @pytest.mark.parametrize(
        "text",
        [
            "voce consegue construir um checkout com Pix?",
            "precisa que a gente implemente integracao com o RDStation",
            "da para voces criarem um relatorio novo?",
            "adiciona um endpoint de webhook",
            "arruma a automacao de follow-up",
            "consegue desenvolver uma tela de proposta?",
        ],
    )
    def test_build_shaped_asks_are_refused(self, wired, text):
        from aios.tools.team_collaboration import _looks_like_build_request

        assert _looks_like_build_request(text) is True, text

    @pytest.mark.parametrize(
        "text",
        [
            "como esta a integracao que voces construiram?",
            "o que voces ja implementaram no checkout?",
            "qual o endpoint que voces usam?",
            "qual a taxa de conversao atual?",
            "quantos deals estao stalled?",
            "qual o relatorio que voces criaram ontem?",
        ],
    )
    def test_questions_pass_through(self, text):
        """Routing trivia into the enforced door would train the owner to ignore
        it, which loses the signal that matters."""
        from aios.tools.team_collaboration import _looks_like_build_request

        assert _looks_like_build_request(text) is False, text

    async def test_the_refusal_names_the_right_door(self, wired):
        """A refusal that does not say where to go leaves the agent stuck."""
        from aios.tools.team_collaboration import AskTeamManagerTool

        tool = AskTeamManagerTool()
        tool._org_id = wired["org"]
        tool._agent_id = wired["caller_id"]
        out = await tool.run(
            to_team="Dev",
            question="voce consegue construir um checkout com Pix?",
        )
        assert out["ok"] is False
        assert out.get("suggested_tool") == "request_build"
        assert "request_build" in out["error"]
        # And nothing reached dev.
        assert wired["posted"] == []

    async def test_a_question_still_reaches_the_other_manager(self, wired):
        """The guard must not cost the teams their normal conversation."""
        from aios.tools.team_collaboration import AskTeamManagerTool

        tool = AskTeamManagerTool()
        tool._org_id = wired["org"]
        tool._agent_id = wired["caller_id"]
        out = await tool.run(to_team="Dev", question="qual o endpoint que voces usam?")
        assert out["ok"] is True, out
        assert out["team"] == "Dev"


# ─── the owner hears about the workday ─────────────────────────────────────

class TestWorkdayDigest:
    async def test_digest_reports_failures_first(self, test_session, monkeypatch):
        from aios.core.workday import WORKDAY_ENABLED_KEY
        from aios.db.engine import async_session
        from aios.tasks import jobs as J

        org = await _org()
        # The master switch is off by default, and an empty board skips the run
        # entirely, so both have to be arranged for the agent to fail at all.
        async with async_session() as sess:
            o = await sess.get(Organization, org)
            o.extra_data = {WORKDAY_ENABLED_KEY: True}
            await sess.commit()

        bot = await _agent(org, "broken-bot")
        await _deal(org, bot, lead_name="needs work")

        class _Boom:
            def __init__(self, agent):
                pass

            async def run(self, conv, msg, db=None, emit=None):
                raise RuntimeError("model timeout")

        monkeypatch.setattr("aios.core.autonomous_agent.AutonomousAgent", _Boom)

        posted: list[str] = []

        async def fake_post(text, targets):
            posted.append(text)
            return True

        async def targets(org_id, team_id=""):
            return ["UOWNER"]

        import aios.core.meetings as meetings

        meetings.post_to_slack = fake_post
        meetings.human_slack_targets = targets

        result = await J.workday_job(None)
        assert result["failed"] == 1
        assert len(posted) == 1
        assert "falharam" in posted[0]
        assert "model timeout" in posted[0]

    async def test_no_digest_when_nothing_happened(self, test_session, monkeypatch):
        """A daily "nothing happened" is how people learn to ignore a channel."""
        from aios.tasks import jobs as J

        posted: list[str] = []

        async def fake_post(text, targets):
            posted.append(text)
            return True

        async def targets(org_id, team_id=""):
            return ["UOWNER"]

        import aios.core.meetings as meetings

        meetings.post_to_slack = fake_post
        meetings.human_slack_targets = targets

        await J.workday_job(None)
        assert posted == []
