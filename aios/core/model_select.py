"""Pick the best OpenRouter model per agent type from the live catalog.

Why this exists: every template ships the same `openai/gpt-4o` (or -mini) that
was reasonable when it was written. Prices and model quality move, so the
question "which model should this kind of agent use?" is answered against the
catalog as it is today, not against a hardcoded list.

What "best" means here is deliberately narrow and checkable: an agent type
declares what it needs (reasoning, agentic tool use, coding, cheap volume,
long context, tools, structured output), and the catalog is scored only on
fields OpenRouter actually publishes — Artificial Analysis indices, price,
context window and supported parameters. No invented benchmark numbers, no
vibe-based taste. A model with no benchmark on the axes a role needs is not
recommended for that role at all, because "fastest-looking model with no
evidence" is exactly the wrong answer for a role that touches money or code.

This module only recommends. It never rewrites an agent's configuration;
changing a live agent's model is an operator decision (and a cost change).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from dataclasses import dataclass, field

CATALOG_TTL_SECONDS = 6 * 60 * 60
_AA = "artificial_analysis"
_INDICES = ("intelligence_index", "coding_index", "agentic_index")

# Suffixes that are priced in batch (not interactive) or are rate-limited free
# tiers. Recommending either for a production agent would misstate latency or
# capacity, so they are not candidates.
_EXCLUDED_SUFFIXES = (":batch", ":free")

# Absolute score anchors (see rank()): frontier score per benchmark family, the
# blended price where the cost score is 0.5, and the context window treated as
# full marks. Fixed on purpose so ranks do not move with the catalog.
_INDEX_SCALE = {"intelligence": 60.0, "coding": 80.0, "agentic": 60.0}
_COST_HALF = 1.0
_MAX_CTX = 1_000_000

# One profile per kind of work. Weights sum to 1. `tools` means the agent's
# template actually calls tools, so a chat-only model cannot do the job.
# `min_context` is what the template's prompt + memory budget needs, rounded up.
PROFILES: dict[str, dict] = {
    # Coordinators read many sub-agent reports and decide; tool calling is the
    # core of the job.
    "orchestrator": {"agentic": 0.40, "intelligence": 0.35, "cost": 0.20, "context": 0.05,
                     "tools": True, "min_context": 64_000},
    "manager": {"agentic": 0.35, "intelligence": 0.40, "cost": 0.20, "context": 0.05,
                "tools": True, "min_context": 64_000},
    # Customer-facing conversation: volume is high and latency matters, but a
    # wrong commitment costs a deal, so quality cannot collapse.
    "sdr": {"intelligence": 0.30, "agentic": 0.30, "cost": 0.35, "context": 0.05,
            "tools": True, "min_context": 32_000},
    # Outbound research: reads many pages, must return structured leads cheaply.
    "prospector": {"intelligence": 0.35, "cost": 0.45, "context": 0.20,
                   "tools": True, "structured": True, "min_context": 64_000},
    "closer": {"intelligence": 0.35, "agentic": 0.30, "cost": 0.30, "context": 0.05,
               "tools": True, "min_context": 32_000},
    "support": {"intelligence": 0.25, "agentic": 0.20, "cost": 0.50, "context": 0.05,
                "tools": True, "min_context": 32_000},
    # Code, SQL and analysis: coding index is the closest real signal.
    "data_scientist": {"coding": 0.40, "intelligence": 0.35, "cost": 0.20, "context": 0.05,
                       "tools": True, "min_context": 128_000},
    "data_analyst": {"coding": 0.25, "intelligence": 0.40, "cost": 0.30, "context": 0.05,
                     "tools": True, "min_context": 64_000},
    "frontend": {"coding": 0.55, "intelligence": 0.25, "cost": 0.15, "context": 0.05,
                 "tools": True, "min_context": 128_000},
    "backend": {"coding": 0.55, "intelligence": 0.25, "cost": 0.15, "context": 0.05,
                "tools": True, "min_context": 128_000},
    # Red/blue review: agentic and coding both matter, then price.
    "review": {"agentic": 0.40, "coding": 0.30, "cost": 0.20, "context": 0.10,
               "tools": True, "min_context": 64_000},
    # Auditors check someone else's output against rules: quality and cost, and
    # they parse structured replies.
    "auditor": {"intelligence": 0.50, "cost": 0.40, "context": 0.10,
                "tools": True, "structured": True, "min_context": 32_000},
    # Background watchers compare metrics and raise flags; cheap and structured.
    "watcher": {"intelligence": 0.35, "cost": 0.55, "context": 0.10,
                "tools": True, "structured": True, "min_context": 32_000},
    # Business teams: writing and coordination, cost-sensitive at volume.
    "business": {"intelligence": 0.35, "agentic": 0.15, "cost": 0.45, "context": 0.05,
                 "tools": True, "min_context": 32_000},
    "custom": {"intelligence": 0.35, "agentic": 0.25, "cost": 0.35, "context": 0.05,
               "tools": True, "min_context": 32_000},
}

# Explicit agent_type -> profile. Anything not listed falls back to "custom".
TYPE_PROFILE: dict[str, str] = {
    "orchestrator": "orchestrator",
    "orchestrator_business": "orchestrator",
    "manager": "manager",
    "manager_sales": "manager",
    "manager_dev": "manager",
    "manager_red": "review",
    "manager_blue": "review",
    "manager_data": "manager",
    "manager_marketing": "business",
    "manager_cs": "business",
    "manager_revops": "business",
    "sdr": "sdr",
    "lead_finder": "prospector",
    "closer": "closer",
    "support": "support",
    "customer_success": "support",
    "data_analyst": "data_analyst",
    "data_scientist": "data_scientist",
    "frontend": "frontend",
    "backend": "backend",
    "red": "review",
    "blue": "review",
    "deal_auditor": "auditor",
    "pricing_guardian": "auditor",
    "human_auditor": "auditor",
    "evidence_compiler": "watcher",
    "performance_watcher": "watcher",
    "marketing": "business",
    "revops": "business",
    "custom": "custom",
}

_cache: dict = {"at": 0.0, "models": None}


@dataclass
class Pick:
    model: str
    score: float
    price_in: float
    price_out: float
    context: int
    indices: dict = field(default_factory=dict)
    reason: str = ""


def profile_for(agent_type: str) -> dict:
    return PROFILES[TYPE_PROFILE.get(agent_type, "custom")]


def _price(model: dict) -> tuple[float, float] | None:
    """USD per 1M input/output tokens, or None when OpenRouter omits it."""
    p = model.get("pricing") or {}
    try:
        return float(p["prompt"]) * 1e6, float(p["completion"]) * 1e6
    except (KeyError, TypeError, ValueError):
        return None


def _aa(model: dict) -> dict:
    return ((model.get("benchmarks") or {}).get(_AA) or {})


def _eligible(model: dict, profile: dict) -> bool:
    if any(model.get("id", "").endswith(s) for s in _EXCLUDED_SUFFIXES):
        return False
    if "text" not in ((model.get("architecture") or {}).get("output_modalities") or []):
        return False
    if (model.get("context_length") or 0) < profile["min_context"]:
        return False
    params = set(model.get("supported_parameters") or [])
    if profile.get("tools") and "tools" not in params:
        return False
    if profile.get("structured") and "structured_outputs" not in params:
        return False
    if _price(model) is None:
        return False
    return True


def rank(agent_type: str, models: list[dict]) -> list[Pick]:
    """Score every eligible model for one agent type, best first.

    Pure function so the scoring can be tested without network or a catalog
    snapshot. Returns [] when no model carries evidence for the role.
    """
    profile = profile_for(agent_type)
    candidates = [m for m in models if _eligible(m, profile)]
    if not candidates:
        return []

    quality_axes = [k for k in ("intelligence", "coding", "agentic") if profile.get(k)]
    index_key = {"intelligence": "intelligence_index", "coding": "coding_index",
                 "agentic": "agentic_index"}

    # The role's main axis must be measured, otherwise the "best" pick is only
    # the cheapest one. Secondary axes may be missing, but a missing benchmark
    # scores 0: an unverified capability is not credited (that is what stops a
    # model with only a price tag from beating a measured one).
    primary = max(quality_axes, key=lambda a: profile[a])
    scored = [m for m in candidates if _aa(m).get(index_key[primary]) is not None]
    if not scored:
        return []

    # Absolute scales, deliberately not relative to the current cohort: a
    # model's rank must not change because an unrelated model entered the
    # catalog. Index scale is the frontier score of that benchmark family (so
    # 1.0 is best-in-class); cost scale makes $1/1M blended ≈ 0.5.
    total_weight = sum(profile[k] for k in (*quality_axes, "cost", "context") if profile.get(k))

    picks: list[Pick] = []
    for model in scored:
        total = 0.0
        for axis in quality_axes:
            value = _aa(model).get(index_key[axis])
            total += profile[axis] * (min(1.0, value / _INDEX_SCALE[axis]) if value else 0.0)
        pin, pout = _price(model)
        blended = pin + pout * 0.5
        total += profile["cost"] * (1.0 / (1.0 + blended / _COST_HALF))
        if profile.get("context"):
            ctx = model.get("context_length") or 0
            total += profile["context"] * (math.log1p(ctx) / math.log1p(_MAX_CTX))
        score = total / total_weight if total_weight else 0.0

        idx = {k: _aa(model).get(index_key[k]) for k in quality_axes}
        picks.append(Pick(model["id"], round(min(1.0, score), 4), pin, pout,
                          model.get("context_length") or 0,
                          {k: v for k, v in idx.items() if v is not None}))

    # Deterministic: higher score, then cheaper, then id.
    picks.sort(key=lambda p: (-p.score, p.price_in + p.price_out, p.model))
    for p in picks:
        p.reason = _why(profile, p)
    return picks


def _why(profile: dict, pick: Pick) -> str:
    bits = []
    names = {"intelligence": "intelligence", "coding": "coding", "agentic": "agentic"}
    for axis, val in pick.indices.items():
        bits.append(f"{names[axis]} {val:g}")
    bits.append(f"${pick.price_in:g}/${pick.price_out:g} per 1M")
    bits.append(f"{pick.context // 1000}k ctx")
    if profile.get("structured"):
        bits.append("structured output")
    return " · ".join(bits)


async def fetch_catalog(force: bool = False) -> list[dict]:
    """OpenRouter's model list, cached in-process. Public endpoint, no API key."""
    now = time.time()
    if not force and _cache["models"] and now - _cache["at"] < CATALOG_TTL_SECONDS:
        return _cache["models"]
    import httpx

    from aios.config import settings

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{settings.openrouter_base_url}/models")
        resp.raise_for_status()
        models = resp.json()["data"]
    _cache.update(at=now, models=models)
    return models


async def recommend(agent_type: str, limit: int = 2, force: bool = False) -> list[Pick]:
    return rank(agent_type, await fetch_catalog(force=force))[:limit]


async def _main() -> None:
    ap = argparse.ArgumentParser(description="Best OpenRouter model per agent type")
    ap.add_argument("--type", action="append", dest="types", help="agent type(s), default all")
    ap.add_argument("--limit", type=int, default=2, help="alternatives per type")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    types = args.types or list(TYPE_PROFILE)
    models = await fetch_catalog(force=args.refresh)
    out = {}
    for t in types:
        picks = rank(t, models)[: args.limit]
        out[t] = [
            {"model": p.model, "score": p.score, "price_in": p.price_in,
             "price_out": p.price_out, "context": p.context, "indices": p.indices}
            for p in picks
        ]
    if args.json:
        print(json.dumps(out, indent=2))
        return
    width = max(len(t) for t in out)
    for t, picks in out.items():
        if not picks:
            print(f"{t:<{width}}  (no model meets the role's requirements)")
            continue
        best = picks[0]
        print(f"{t:<{width}}  {best['model']:<38} ${best['price_in']:g}/${best['price_out']:g}"
              f"  {best['context'] // 1000}k  {best['indices']}")
        for alt in picks[1:]:
            print(f"{'':<{width}}  ↳ {alt['model']:<36} ${alt['price_in']:g}/{alt['price_out']:g}")


if __name__ == "__main__":
    asyncio.run(_main())
