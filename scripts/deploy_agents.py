#!/usr/bin/env python3
"""Deploy and verify an org's agents with DB-read-only dry run by default.

Only ``deploy_and_verify`` may set ``Agent.status = "active"``. This CLI probes
each agent first; a failed probe never reaches that writer. Archived agents are
skipped even when named explicitly.

Exit codes: 0 all ok / no-op, 1 unexpected fatal error, 2 preflight refused,
3 one or more agents failed.

Example:
    python scripts/deploy_agents.py --org-id ORG --backup /tmp/agents-before.json
    python scripts/deploy_agents.py --org-id ORG --backup /tmp/agents-before-2.json --apply --agent sales-sdr
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from aios.config import settings
from aios.core.deployment import deploy_and_verify, probe_agent
from aios.core.providers import provider_health
from aios.db.backend import db_session
from aios.db.models import Agent, Organization

EXIT_OK = 0
EXIT_FATAL = 1
EXIT_PREFLIGHT = 2
EXIT_PARTIAL = 3
MAX_CONCURRENCY = 8

HEALTH_KEYS = ("provider", "model", "available", "credentials_configured", "circuit")


def _clean(error: Exception) -> str:
    return str(error).replace("\n", " ")[:300]


def _concurrency(value: str) -> int:
    number = int(value)
    if not 1 <= number <= MAX_CONCURRENCY:
        raise argparse.ArgumentTypeError(f"must be 1..{MAX_CONCURRENCY}")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--backup", required=True, type=Path, help="new JSON status snapshot path; never overwritten")
    parser.add_argument("--agent", action="append", default=[], help="agent id or exact name; repeatable")
    parser.add_argument("--concurrency", type=_concurrency,
                        default=min(max(1, settings.fleet_verify_concurrency), MAX_CONCURRENCY))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="apply", action="store_false", help="default: probe nothing, no DB writes")
    mode.add_argument("--apply", dest="apply", action="store_true", help="probe and deploy")
    parser.set_defaults(apply=False)
    return parser


async def _load_agents(org_id: str) -> list[Agent] | None:
    async with db_session() as db:
        if await db.get(Organization, org_id) is None:
            return None
        rows = await db.execute(
            select(Agent).where(Agent.org_id == org_id).order_by(Agent.name)
        )
        return list(rows.scalars().all())


def _select_targets(agents: list[Agent], requested: list[str]) -> tuple[list[Agent], list[str], list[str]]:
    by_token = {}
    for agent in agents:
        by_token.setdefault(agent.id, agent)
        by_token.setdefault(agent.name, agent)

    if not requested:
        candidates = [agent for agent in agents if agent.status != "archived"]
        return candidates, [], []

    selected, skipped, missing = [], [], []
    for token in requested:
        agent = by_token.get(token)
        if agent is None:
            missing.append(token)
        elif agent.status == "archived":
            skipped.append(token)
        else:
            selected.append(agent)
    unique, seen = [], set()
    for agent in selected:
        if agent.id not in seen:
            seen.add(agent.id)
            unique.append(agent)
    return unique, skipped, missing


def _credential_preflight(models: list[str]) -> tuple[dict, list[str]]:
    """Check the credential probe_agent will use (provider defaults/settings)."""
    checked, missing = {}, []
    for model in sorted(set(models)):
        try:
            health = provider_health(model)
        except Exception as exc:
            checked[model] = {"available": False, "error": _clean(exc)}
            missing.append(model)
            continue
        checked[model] = {key: health.get(key) for key in HEALTH_KEYS}
        if not health.get("available"):
            missing.append(model)
    return checked, missing


def _snapshot(org_id: str, mode: str, agents: list[Agent], preflight: dict) -> dict:
    return {
        "org_id": org_id,
        "mode": mode,
        "agents": [
            {
                "id": agent.id,
                "name": agent.name,
                "status": agent.status,
                "model": (agent.llm_config or {}).get("model"),
            }
            for agent in agents
        ],
        "credential_preflight": preflight,
    }


async def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    mode = "apply" if args.apply else "dry-run"

    agents = await _load_agents(args.org_id)
    if agents is None:
        print(f"org not found: {args.org_id}", file=sys.stderr)
        return EXIT_PREFLIGHT

    targets, skipped, missing = _select_targets(agents, args.agent)
    if missing:
        print(f"agent not found in org: {', '.join(missing)}", file=sys.stderr)
        return EXIT_PREFLIGHT

    preflight, unusable = _credential_preflight(
        [(agent.llm_config or {}).get("model") or "" for agent in targets]
    )
    if unusable:
        print(f"provider credential preflight failed for: {', '.join(unusable)}", file=sys.stderr)
        return EXIT_PREFLIGHT

    snapshot = _snapshot(args.org_id, mode, agents, preflight)
    try:
        with args.backup.open("x", encoding="utf-8") as handle:
            json.dump(snapshot, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except FileExistsError:
        print(f"backup already exists: {args.backup}", file=sys.stderr)
        return EXIT_PREFLIGHT
    except OSError as exc:
        print(f"backup write failed: {_clean(exc)}", file=sys.stderr)
        return EXIT_PREFLIGHT

    if not args.apply:
        print(json.dumps({
            "org_id": args.org_id,
            "mode": mode,
            "backup": str(args.backup),
            "skipped_archived": skipped,
            "would_deploy": [agent.id for agent in targets],
            "results": [],
        }, indent=2, sort_keys=True))
        return EXIT_OK

    semaphore = asyncio.Semaphore(args.concurrency)
    user_id = getpass.getuser()

    async def one(agent: Agent) -> dict:
        entry = {"id": agent.id, "name": agent.name, "ok": False,
                 "model": (agent.llm_config or {}).get("model"),
                 "error": None, "status_after": agent.status, "latency_ms": None}
        async with semaphore:
            try:
                async with db_session() as db:
                    fresh = await db.get(Agent, agent.id)
                    if fresh is None or fresh.org_id != args.org_id:
                        raise RuntimeError("agent not found in this org")
                    # Read-only gate: no failed probe reaches the only active-status writer.
                    evidence = await probe_agent(fresh)
                    result = await deploy_and_verify(db, fresh, args.org_id, user_id=user_id)
                entry.update(ok=True, status_after=fresh.status,
                             latency_ms=(evidence or result.get("evidence") or {}).get("latency_ms"))
            except Exception as exc:
                entry["error"] = _clean(exc)
        return entry

    results = await asyncio.gather(*(one(agent) for agent in targets))
    failed = [entry["id"] for entry in results if not entry["ok"]]
    print(json.dumps({
        "org_id": args.org_id,
        "mode": mode,
        "backup": str(args.backup),
        "skipped_archived": skipped,
        "deployed": [entry["id"] for entry in results if entry["ok"]],
        "failed": failed,
        "results": results,
    }, indent=2, sort_keys=True))
    return EXIT_PARTIAL if failed else EXIT_OK


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(EXIT_FATAL)
