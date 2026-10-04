"""Stand up the company: one cross-team coordinator and the missing functions.

Templates describe agents; something has to actually create them. This is that
something, and it is idempotent by construction -- it looks for the marker it
writes before it creates anything, so running it twice does not produce two
orchestrators arguing about the same pipeline.

The coordinator is deliberately *not* placed on a team. Its whole job is the
space between teams, so attaching it to one would make it a member of that team
and `ask_team_manager` would refuse to let it talk to anyone else (it refuses to
let a team ask itself). It is found by its `extra_data` marker instead.
"""

import logging

logger = logging.getLogger(__name__)

ORCHESTRATOR_MARKER = "business_orchestrator"

# key -> (display name, worker template, manager template)
BUSINESS_TEAMS = (
    {"key": "marketing", "name": "Marketing", "worker": "marketing", "manager": "manager_marketing"},
    {"key": "customer_success", "name": "Customer Success", "worker": "customer_success", "manager": "manager_cs"},
    {"key": "revops", "name": "Receita e Operações", "worker": "revops", "manager": "manager_revops"},
)


def _marker(kind: str, key: str) -> dict:
    return {"business_setup": kind, "business_key": key}


async def _find_agent(org_id: str, agent_type: str, kind: str, key: str):
    """Find an agent this bootstrap created before, by its marker."""
    from sqlalchemy import select

    from aios.db.engine import async_session
    from aios.db.models import Agent

    async with async_session() as sess:
        rows = (
            await sess.execute(
                select(Agent).where(Agent.org_id == org_id, Agent.agent_type == agent_type)
            )
        ).scalars().all()

    for a in rows:
        extra = a.extra_data or {}
        if extra.get("business_setup") == kind and extra.get("business_key") == key:
            return a
    return None


async def _create_agent(org_id: str, name: str, template: str, extra: dict):
    from aios.db.engine import async_session
    from aios.db.models import Agent
    from aios.templates import apply_template

    cfg = apply_template(template)
    async with async_session() as sess:
        agent = Agent(
            org_id=org_id,
            name=name,
            agent_type=cfg.get("agent_type", template),
            system_prompt=cfg.get("system_prompt", ""),
            llm_config=cfg.get("llm_config", {}),
            tools=list(cfg.get("tools", [])),
            memory_config=cfg.get("memory_config", {}),
            governance_config=cfg.get("governance_config", {}),
            extra_data=extra,
            # Left active on purpose: an agent created to run the business that
            # cannot act is a config error the operator can see in the UI. The
            # daily workday board is separately off until they switch it on.
            status="active",
        )
        sess.add(agent)
        await sess.commit()
        return agent.id, agent.name


async def ensure_business_orchestrator(org_id: str) -> tuple[str, bool]:
    """Create the cross-team coordinator if it is missing.

    Returns (agent_id, created).
    """
    existing = await _find_agent(org_id, "orchestrator", ORCHESTRATOR_MARKER, ORCHESTRATOR_MARKER)
    if existing is not None:
        return existing.id, False
    agent_id, name = await _create_agent(
        org_id, "Coordenador Geral", "orchestrator_business",
        _marker(ORCHESTRATOR_MARKER, ORCHESTRATOR_MARKER),
    )
    logger.info("business orchestrator created org=%s agent=%s", org_id, name)
    return agent_id, True


async def ensure_business_team(org_id: str, spec: dict) -> dict:
    """Create one team (worker + manager + links) if any of it is missing."""
    from sqlalchemy import select

    from aios.db.engine import async_session
    from aios.db.models import Team, team_agents

    key = spec["key"]

    async with async_session() as sess:
        existing = (
            await sess.execute(select(Team).where(Team.org_id == org_id, Team.name == spec["name"]))
        ).scalars().first()
    if existing is not None:
        return {"key": key, "team": spec["name"], "created": False, "reason": "team exists"}

    worker = await _find_agent(org_id, "custom", "worker", key)
    worker_created = False
    if worker is None:
        worker_id, worker_name = await _create_agent(
            org_id, f"{spec['name']} — Analista", spec["worker"], _marker("worker", key)
        )
        worker_created = True
    else:
        worker_id, worker_name = worker.id, worker.name

    manager = await _find_agent(org_id, "manager", "manager", key)
    manager_created = False
    if manager is None:
        manager_id, manager_name = await _create_agent(
            org_id, f"Gerente de {spec['name']}", spec["manager"], _marker("manager", key)
        )
        manager_created = True
    else:
        manager_id, manager_name = manager.id, manager.name

    async with async_session() as sess:
        team = Team(
            org_id=org_id,
            name=spec["name"],
            routing_strategy="hierarchical",
            orchestrator_agent_id=worker_id,
            manager_agent_id=manager_id,
            handoff_config={
                "enabled": True,
                "manager_handles": ["coordination", "escalation", "quality_review"],
                "auto_escalate": True,
                "handoff_chain": "orchestrator->manager->agent",
            },
            extra_data={"business_setup": "team", "business_key": key},
        )
        sess.add(team)
        await sess.flush()
        for pri, aid in enumerate([worker_id, manager_id]):
            await sess.execute(
                team_agents.insert().values(team_id=team.id, agent_id=aid, priority=pri)
            )
        await sess.commit()

    logger.info(
        "business team created org=%s team=%s worker=%s manager=%s",
        org_id, spec["name"], worker_name, manager_name,
    )
    return {
        "key": key,
        "team": spec["name"],
        "team_id": team.id,
        "worker": worker_name,
        "manager": manager_name,
        "created": True,
        "worker_created": worker_created,
        "manager_created": manager_created,
    }


async def ensure_business_setup(org_id: str) -> dict:
    """Idempotently stand up the coordinator and the three missing functions.

    Safe to call on every deploy. Each step checks for its own marker first, so
    this creates what is missing and leaves everything else alone.
    """
    if not org_id:
        raise ValueError("org_id is required")

    orch_id, orch_created = await ensure_business_orchestrator(org_id)

    teams = []
    for spec in BUSINESS_TEAMS:
        try:
            teams.append(await ensure_business_team(org_id, spec))
        except Exception:
            # One team failing must not leave the org with half a company.
            logger.exception("business team setup failed org=%s key=%s", org_id, spec["key"])
            teams.append({"key": spec["key"], "created": False, "reason": "error"})

    return {
        "org_id": org_id,
        "orchestrator_agent_id": orch_id,
        "orchestrator_created": orch_created,
        "teams": teams,
        "created_teams": sum(1 for t in teams if t.get("created")),
    }