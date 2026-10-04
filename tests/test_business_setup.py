"""The company layer: a cross-team coordinator, three new functions, and the
bootstrap that actually creates them.

Two things were true before this and both were the problem:

- every template's tool list was checked against the real registry, because a
  template naming a tool that does not exist ships an agent that silently
  cannot do its job;
- nothing ever *created* the agents, so "the orchestrator we never created" was
  a template nobody instantiated. The bootstrap is idempotent, and that is the
  property worth testing: running it twice must not produce two coordinators.
"""

import pytest

from aios.db.models import Agent, Organization, Team, team_agents

NEW_TEMPLATES = (
    "orchestrator_business",
    "manager_marketing",
    "marketing",
    "manager_cs",
    "customer_success",
    "manager_revops",
    "revops",
)


# ─── templates ─────────────────────────────────────────────────────────────

class TestNewTemplates:
    @pytest.mark.parametrize("name", NEW_TEMPLATES)
    def test_registered(self, name):
        from aios.templates import TEMPLATES

        assert name in TEMPLATES

    @pytest.mark.parametrize("name", NEW_TEMPLATES)
    def test_every_tool_exists(self, name):
        """The defect this codebase already paid for: a prompt promising a tool
        that is not registered ships an agent that cannot do its job."""
        import aios.tools  # noqa: F401
        from aios.templates import TEMPLATES
        from aios.tools.registry import TOOL_REGISTRY

        missing = [t for t in TEMPLATES[name]["tools"] if t not in TOOL_REGISTRY]
        assert not missing, f"{name} names tools that do not exist: {missing}"

    @pytest.mark.parametrize("name", NEW_TEMPLATES)
    def test_has_a_real_prompt(self, name):
        from aios.templates import TEMPLATES

        assert len(TEMPLATES[name]["system_prompt"]) > 400

    @pytest.mark.parametrize("name", NEW_TEMPLATES)
    def test_tools_actually_load(self, name):
        import aios.tools  # noqa: F401
        from aios.core.tools import ToolEngine
        from aios.templates import TEMPLATES

        engine = ToolEngine(TEMPLATES[name]["tools"])
        assert not engine.missing, f"{name} names tools that will not load: {engine.missing}"
        assert len(engine.tools) == len(TEMPLATES[name]["tools"])

    def test_coordinator_can_reach_every_team_and_the_owner(self):
        """Without these three it cannot do its job: talk to managers, force a
        build request through, and reach the human."""
        from aios.templates import TEMPLATES

        tools = set(TEMPLATES["orchestrator_business"]["tools"])
        assert {"ask_team_manager", "request_build", "notify_human"} <= tools

    def test_managers_can_raise_a_build_request(self):
        """Sales and Dev managers are the two the owner named; the other managers
        need the same door or they can only ask informally."""
        from aios.templates import TEMPLATES

        for name in ("manager_marketing", "manager_cs", "manager_revops"):
            assert "request_build" in TEMPLATES[name]["tools"], name
            assert "ask_team_manager" in TEMPLATES[name]["tools"], name
            assert "notify_human" in TEMPLATES[name]["tools"], name

    def test_prompts_are_not_mojibake(self):
        """These prompts are read by the model and by humans in the UI; a stray
        CJK glyph or missing space ships as visible garbage."""
        from aios.templates import TEMPLATES

        for name in NEW_TEMPLATES:
            text = TEMPLATES[name]["system_prompt"]
            bad = [ch for ch in text if ord(ch) > 0x2FFF]
            assert not bad, f"{name} contains unexpected characters: {set(bad)}"


# ─── bootstrap ─────────────────────────────────────────────────────────────

async def _org(slug: str) -> str:
    from aios.db.engine import async_session

    async with async_session() as sess:
        o = Organization(name=slug, slug=slug)
        sess.add(o)
        await sess.commit()
        return o.id


class TestBootstrap:
    async def test_creates_the_coordinator_and_three_teams(self, test_session):
        from aios.core.org_bootstrap import ensure_business_setup

        org = await _org("bs-1")
        out = await ensure_business_setup(org)

        assert out["orchestrator_created"] is True
        assert out["created_teams"] == 3

        from aios.db.engine import async_session
        from sqlalchemy import select

        async with async_session() as sess:
            agents = (await sess.execute(select(Agent).where(Agent.org_id == org))).scalars().all()
            teams = (await sess.execute(select(Team).where(Team.org_id == org))).scalars().all()

        # Filtered in Python: the marker lives in a JSON column and the portable
        # way to read it is the same one the bootstrap itself uses.
        orch = [
            a for a in agents
            if (a.extra_data or {}).get("business_setup") == "business_orchestrator"
        ]
        assert len(orch) == 1
        assert len(teams) == 3
        assert {t.name for t in teams} == {"Marketing", "Customer Success", "Receita e Operações"}

    async def test_running_twice_creates_nothing_new(self, test_session):
        """Two coordinators arguing about the same pipeline is worse than one
        missing, so the marker check is the whole point of this function."""
        from aios.core.org_bootstrap import ensure_business_setup
        from aios.db.engine import async_session
        from sqlalchemy import func, select

        org = await _org("bs-2")
        first = await ensure_business_setup(org)
        second = await ensure_business_setup(org)

        assert second["orchestrator_created"] is False
        assert second["created_teams"] == 0
        assert first["created_teams"] == 3

        async with async_session() as sess:
            n_agents = (
                await sess.execute(
                    select(func.count()).select_from(Agent).where(Agent.org_id == org)
                )
            ).scalar()
            n_teams = (
                await sess.execute(
                    select(func.count()).select_from(Team).where(Team.org_id == org)
                )
            ).scalar()
        # 1 coordinator + 3 teams x (worker + manager)
        assert n_agents == 7
        assert n_teams == 3

    async def test_each_team_has_a_manager_and_its_worker(self, test_session):
        """A team with no manager cannot be asked anything, so `ask_team_manager`
        and `request_build` both refuse it."""
        from aios.core.org_bootstrap import ensure_business_setup
        from aios.db.engine import async_session
        from sqlalchemy import select

        org = await _org("bs-3")
        await ensure_business_setup(org)

        async with async_session() as sess:
            teams = (await sess.execute(select(Team).where(Team.org_id == org))).scalars().all()
            for t in teams:
                assert t.manager_agent_id, f"{t.name} has no manager"
                assert t.orchestrator_agent_id, f"{t.name} has no orchestrator"
                members = (
                    await sess.execute(
                        select(team_agents.c.agent_id).where(team_agents.c.team_id == t.id)
                    )
                ).scalars().all()
                assert set(members) == {t.manager_agent_id, t.orchestrator_agent_id}
                mgr = await sess.get(Agent, t.manager_agent_id)
                assert mgr.agent_type == "manager"
                assert "request_build" in (mgr.tools or [])

    async def test_coordinator_is_not_on_a_team(self, test_session):
        """Its whole job is the space between teams. Attached to one, the
        cross-team guard would treat every other team as an outsider and the
        coordinator could not coordinate."""
        from aios.core.org_bootstrap import ensure_business_setup
        from aios.db.engine import async_session
        from sqlalchemy import select

        org = await _org("bs-4")
        out = await ensure_business_setup(org)

        async with async_session() as sess:
            rows = (
                await sess.execute(
                    select(team_agents.c.team_id).where(
                        team_agents.c.agent_id == out["orchestrator_agent_id"]
                    )
                )
            ).scalars().all()
        assert rows == []

    async def test_never_crosses_tenants(self, test_session):
        from aios.core.org_bootstrap import ensure_business_setup
        from aios.db.engine import async_session
        from sqlalchemy import func, select

        a = await _org("bs-a")
        b = await _org("bs-b")
        await ensure_business_setup(a)
        await ensure_business_setup(b)

        async with async_session() as sess:
            for org, expected in ((a, 7), (b, 7)):
                n = (
                    await sess.execute(
                        select(func.count()).select_from(Agent).where(Agent.org_id == org)
                    )
                ).scalar()
                assert n == expected, org

    async def test_requires_an_org(self):
        from aios.core.org_bootstrap import ensure_business_setup

        with pytest.raises(ValueError):
            await ensure_business_setup("")

    async def test_agents_are_active_so_they_can_act(self, test_session):
        """Left draft, the company would exist and do nothing. The daily board
        is a separate switch, off by default."""
        from aios.core.org_bootstrap import ensure_business_setup
        from aios.db.engine import async_session
        from sqlalchemy import select

        org = await _org("bs-5")
        await ensure_business_setup(org)

        async with async_session() as sess:
            agents = (await sess.execute(select(Agent).where(Agent.org_id == org))).scalars().all()
        assert agents
        assert all(a.status == "active" for a in agents)

    def test_the_two_named_managers_can_open_the_door(self):
        """The owner named Sales and Dev specifically. Both managers already had
        ask_team_manager and notify_human, so the protocol was reachable in
        spirit and impossible in practice -- and that gap was invisible because
        no test looked at what a manager can actually call.
        """
        from aios.templates import TEMPLATES

        for name in ("manager_sales", "manager_dev"):
            tools = TEMPLATES[name]["tools"]
            assert "request_build" in tools, f"{name} cannot raise a build request"
            prompt = TEMPLATES[name]["system_prompt"]
            assert "request_build" in prompt, f"{name} is never told about the protocol"

    def test_sales_manager_is_told_judgement_needs_a_number(self):
        """Otherwise it reaches for the tool, gets refused, and the retry loop
        burns tokens without ever producing a real request."""
        from aios.templates import TEMPLATES

        prompt = TEMPLATES["manager_sales"]["system_prompt"]
        low = prompt.lower()
        assert "sem numero" in low or "sem número" in low
