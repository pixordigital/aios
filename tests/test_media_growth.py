"""Focused checks for Media & Growth prompts, not-ready roles, and seed idempotency.

No conftest, no LLM, no prod DB: later-phase roles are draft specs and every
model-related path is left untouched here.
"""

import sys
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import scripts.seed_media_growth as seed_script
from aios.db.models import Agent, AgentVersion, Base, Organization, Team, team_agents
from aios.media_growth import (
    PHASE1_ROLES,
    PHASE2_ROLES,
    PHASE3_ROLES,
    ROLE_PHASES,
    _self_check,
    agent_config,
    analyze_performance,
    phase2_review_workflow_spec,
    phase3_distribution_analytics_workflow_spec,
    prepare_distribution,
    review_content,
)
from aios.tools.registry import TOOL_REGISTRY


def test_media_manager_prompt_uses_only_real_cross_team_targets():
    cfg = agent_config("Media Manager")
    prompt = cfg["system_prompt"]

    # Names passed to ask_team_manager: exact DB names, not display labels.
    for target in ("sales", "data", "dev", "Customer Success", "Receita e Operações"):
        assert target in prompt
    for label in ("Sales", "Data & Analytics", "Engineering", "Revenue & Operations"):
        assert label in prompt

    assert "Inteligência e Conteúdo pertencem ao seu próprio time `media`" in prompt
    assert "notify_human" in prompt
    assert "ask_team_manager" in cfg["tools"]
    assert "notify_human" in cfg["tools"]

    # No own-team or non-existent-team destinations.
    assert "LIA" not in prompt
    assert "Delivery" not in prompt
    assert "times de Inteligência, Conteúdo" not in prompt


def test_later_phase_specs_are_not_ready_and_use_existing_tools():
    for role in (*PHASE2_ROLES, *PHASE3_ROLES):
        cfg = agent_config(role)
        gov = cfg["governance_config"]
        assert cfg["status"] == "draft"
        assert cfg["agent_type"] == "custom"
        assert gov["workflow_status"] == "not_ready"
        assert gov["human_gate"] is True
        assert gov["autonomous"] is False
        assert not gov.get("can_publish", False)
        assert set(cfg["tools"]) <= set(TOOL_REGISTRY)


def test_media_growth_self_check():
    _self_check()


def test_phase2_review_workflow_nodes_and_approval_gate():
    spec = phase2_review_workflow_spec()

    assert spec == phase2_review_workflow_spec()  # deterministic
    assert spec["status"] == "draft"
    assert spec["workflow_status"] == "not_ready"
    assert spec["human_gate"] is True
    assert spec["autonomous"] is False
    assert spec["external_side_effects"] == []

    nodes = {n["id"]: n for n in spec["nodes"]}
    assert set(nodes) == {"review_draft", "human_approval"}
    assert nodes["review_draft"]["handler"] is review_content
    assert nodes["human_approval"]["handler"] is None
    assert nodes["human_approval"]["depends_on"] == ["review_draft"]


def test_phase3_distribution_analytics_workflow_has_no_side_effects():
    spec = phase3_distribution_analytics_workflow_spec()

    assert spec == phase3_distribution_analytics_workflow_spec()  # deterministic
    assert spec["status"] == "draft"
    assert spec["workflow_status"] == "not_ready"
    assert spec["human_gate"] is True
    assert spec["autonomous"] is False
    assert spec["external_side_effects"] == []

    nodes = {n["id"]: n for n in spec["nodes"]}
    assert set(nodes) == {"prepare_distribution", "human_approval", "analyze_performance"}
    assert nodes["prepare_distribution"]["handler"] is prepare_distribution
    assert nodes["analyze_performance"]["handler"] is analyze_performance
    assert nodes["human_approval"]["handler"] is None
    assert nodes["human_approval"]["depends_on"] == ["prepare_distribution"]
    assert nodes["analyze_performance"]["depends_on"] == ["human_approval"]
    assert not any(token in n["id"] for n in spec["nodes"] for token in ("publish", "send", "dm"))

    artifact = nodes["prepare_distribution"]["handler"](
        "x", {"approved_by": "ana", "approved_at": "2026-01-01"}
    )
    assert artifact["external_side_effects"] == []
    assert nodes["prepare_distribution"]["handler"]("x", {})["ok"] is False
    assert "qualified" in nodes["analyze_performance"]["handler"]([])["recommendation"]


@pytest.mark.asyncio
async def test_seed_media_growth_is_idempotent(monkeypatch, capsys):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        session.add(Organization(name="Media Seed Test", slug="media-seed-test"))
        await session.commit()

    @asynccontextmanager
    async def fake_db_session():
        async with Session() as session:
            yield session

    monkeypatch.setattr(seed_script, "db_session", fake_db_session)

    async def run(*args):
        monkeypatch.setattr(sys, "argv", ["seed_media_growth", *args])
        code = await seed_script.main()
        out = capsys.readouterr().out.strip()
        assert code == 0, out
        return out

    common = ("--org-slug", "media-seed-test", "--apply", "--include-later-phases")
    first = await run(*common)
    assert "agents_created=7" in first
    assert "versions_created=7" in first
    assert "teams_created=1" in first
    assert "links_added=7" in first

    second = await run(*common)
    assert "agents_created=0" in second
    assert "versions_created=0" in second
    assert "teams_created=0" in second
    assert "links_added=0" in second
    assert "links_removed=0" in second

    # Default stays Phase 1 only; dry-run proposes removing later-phase links
    # but must not plan new agents for them.
    default_dry_run = await run("--org-slug", "media-seed-test")
    assert "+ agent Quality & Risk Reviewer" not in default_dry_run
    assert "- link Quality & Risk Reviewer -> media" in default_dry_run

    async with Session() as session:
        agents = (await session.execute(select(Agent))).scalars().all()
        versions = (await session.execute(select(AgentVersion))).scalars().all()
        teams = (await session.execute(select(Team))).scalars().all()
        links = (await session.execute(select(team_agents))).all()

    assert len(agents) == 7
    assert len(versions) == 7
    assert len(teams) == 1
    assert len(links) == 7
    later = {a.name: a for a in agents if a.name in (*PHASE2_ROLES, *PHASE3_ROLES)}
    for role, phase in ROLE_PHASES.items():
        if phase == 1:
            continue
        assert later[role].status == "draft"
        assert later[role].extra_data["media_growth_phase"] == phase
        assert later[role].extra_data["media_growth_workflow"] == "not_ready"
    assert set(PHASE1_ROLES) <= {a.name for a in agents}
    await engine.dispose()
