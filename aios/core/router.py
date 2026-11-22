"""Model routing: pick a model per call from signals we already have.

The honesty problem with any router: if you guess wrong about difficulty you
either overpay (always picking the frontier model) or ship a degraded answer
(picking a cheap model for work that needed the frontier one). Both are worse
than the status quo.

So this module does not classify difficulty. It does two things that cannot be
wrong in the same way:

  1. `route()` only ever *downgrades* on signals that are unambiguous — a short
     context with no tools cannot be a frontier-model workload — and returns
     the configured model unchanged whenever the signal is missing, unknown or
     ambiguous. Missing means missing: a sentinel such as `context_tokens=0` is
     treated as "not measured", never as "this request is tiny". The default is
     "no change", so a wrong guess can never be worse than what the operator
     asked for.

  2. `should_escalate()` upgrades when the run *demonstrably* failed: empty
     output, a malformed tool call, or the iteration budget running out. That
     is evidence, not a prediction, so quality is not traded away for the
     cheaper price — it is verified after the fact and repaired.

No LLM call is involved. A classifier would cost money and latency on every
request to save money on some of them, and it would be wrong exactly when it
matters most.

Deliberately not implemented: learning weights from historical outcomes. The
escalation counter below is the hook for it, but tuning it needs real traffic
across model versions, and a stale weight table is worse than none.
"""

import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock

from aios.config import MODEL_ROLE_MIN_TIER, MODEL_TIERS

# Ordered cheapest → most capable. Index is the escalation ladder.
TIERS = MODEL_TIERS

ROLE_MIN_TIER = MODEL_ROLE_MIN_TIER

# Per-request org context for runtime registry enforcement. Set by API/middleware
# when available; absent in background jobs -> backward-compatible fallback.
current_org_id: ContextVar[str | None] = ContextVar("router_org_id", default=None)
current_org_extra: ContextVar[dict | None] = ContextVar("router_org_extra", default=None)


# Tools whose effects are irreversible or externally visible. Routing one of
# these to a cheap model is how you get a confidently wrong answer emailed to a
# customer or written to a live database, so they pin the tier upward.
_CONSEQUENTIAL_TOOLS = frozenset(
    {
        "send_email",
        "send_whatsapp",
        "send_telegram",
        "make_voice_call",
        "sql_query",
        "etl_url",
        "http_post",
        "http_put",
        "http_patch",
        "execute_code",
        "python_sandbox",
    }
)

# A short exchange with no tools is extraction/summarization/lookup, not
# reasoning. Above this many tokens the prompt carries enough context that the
# cheap model starts dropping the instruction.
CHEAP_CTX_TOKENS = 4_000


@dataclass
class RouteDecision:
    """Why a call got the model it got. `changed` is False for a no-op."""

    model: str
    tier: str
    reason: str
    changed: bool = False
    # "hold" | "down" | "up". Direction is explicit rather than inferred from
    # `changed`, because an escalation also sets changed=True and lumping the
    # two together put cost increases into the "saved money" counter.
    kind: str = "hold"
    escalated_from: str | None = None
    signals: dict = field(default_factory=dict)
    policy: dict = field(default_factory=dict)


def _tier_index(model: str) -> int:
    """Position of `model` on the ladder; unknown models sort to the top.

    An unrecognised model is treated as the most capable thing we know about,
    so a newly added model is never silently routed *below* the operator's
    configuration.
    """
    try:
        return TIERS.index(model)
    except ValueError:
        return len(TIERS) - 1


def is_routable(model: str | None) -> bool:
    """Only models on the ladder may be re-chosen.

    A model we cannot place on the ladder is left strictly alone. Collapsing
    unknown models onto a rung is the trap here: it does not merely "hold the
    tier", it *replaces* the operator's model with whichever model happens to
    sit on the top rung — so configuring `anthropic/claude-opus-4` silently
    became a call to `openai/gpt-4o`, a different vendor with different
    behaviour and a different price. Not touching it is the only safe answer.
    """
    return model in TIERS


def _org_model_policy(org_extra: dict | None) -> dict:
    extra = org_extra or {}
    policy = extra.get("model_policy") or {}
    if not isinstance(policy, dict):
        policy = {}
    # explicit allow/deny lists; empty means no restriction
    allow = policy.get("allowed_models") or extra.get("allowed_models") or []
    deny = policy.get("denied_models") or extra.get("denied_models") or []
    if isinstance(allow, str):
        allow = [allow]
    if isinstance(deny, str):
        deny = [deny]
    return {
        "allowed_models": [m for m in allow if isinstance(m, str) and m],
        "denied_models": [m for m in deny if isinstance(m, str) and m],
        "require_registry_approval": bool(policy.get("require_registry_approval", False)),
        "privacy_required": bool(policy.get("privacy_required", True)),
        "contract_required": bool(policy.get("contract_required", True)),
    }


def _policy_allows_model(model: str, org_extra: dict | None) -> tuple[bool, str]:
    policy = _org_model_policy(org_extra)
    if model in policy["denied_models"]:
        return False, f"model denied by org policy ({model})"
    allowed = policy["allowed_models"]
    if allowed and model not in allowed:
        return False, f"model not in org allowlist ({model})"
    return True, ""


def _registry_allows_model(model: str, entries: list | None, org_extra: dict | None) -> tuple[bool, str, dict]:
    """Fail-closed only when registry is being enforced/has entries.

    Backward compat: no entries and no require_registry_approval => allow.
    """
    policy = _org_model_policy(org_extra)
    rows = list(entries or [])
    if not rows:
        if policy["require_registry_approval"]:
            return False, "no approved registry entries for org policy", {"registry_enforced": True}
        return True, "no registry entries — backward-compatible fallback", {"registry_enforced": False}
    match = None
    for e in rows:
        key = getattr(e, "model_key", None)
        if key == model:
            match = e
            break
    if match is None:
        # Registry exists but model not registered: treat as not eligible when enforcement active.
        return False, f"model not in approved registry ({model})", {"registry_enforced": True}
    if not getattr(match, "approved", False):
        return False, f"registry model not approved ({model})", {"registry_enforced": True}
    if policy["privacy_required"] and not getattr(match, "privacy_ok", True):
        return False, f"registry model fails privacy ({model})", {"registry_enforced": True}
    if policy["contract_required"] and not getattr(match, "contract_ok", True):
        return False, f"registry model fails contract ({model})", {"registry_enforced": True}
    return True, "registry approved", {
        "registry_enforced": True,
        "registry_model_key": getattr(match, "model_key", None),
        "registry_tier": getattr(match, "tier", None),
    }


def model_runtime_eligible(
    model: str | None,
    *,
    org_extra: dict | None = None,
    registry_entries: list | None = None,
) -> tuple[bool, str, dict]:
    if not model:
        return False, "model missing", {}
    ok, reason = _policy_allows_model(model, org_extra)
    if not ok:
        return False, reason, {"policy": _org_model_policy(org_extra)}
    ok, reason, meta = _registry_allows_model(model, registry_entries, org_extra)
    if not ok:
        return False, reason, meta
    return True, reason, meta


def route(
    model: str | None,
    *,
    role: str | None = None,
    context_tokens: int = 0,
    tools: list | None = None,
    autonomy: str = "autonomous",
    max_tokens: int = 4096,
    min_tier: str | None = None,
    org_extra: dict | None = None,
    registry_entries: list | None = None,
) -> RouteDecision:
    """Choose the model for one call, now considering the caller's role.

    `role` can be used to enforce a minimum tier based on the agent's responsibilities.
    The function respects all existing signals and still only downgrades when safe.
    """
    """Choose the model for one call.

    `model` is what the operator configured. It is returned unchanged unless
    every signal says the work is small.
    """
    # None means "no model configured". Normalizing once here keeps every
    # RouteDecision str-typed downstream instead of sprinkling guards.
    if model is None:
        model = ""
    tool_names = {t.get("function", {}).get("name", "") for t in (tools or [])}
    signals = {
        "context_tokens": context_tokens,
        "tools": len(tool_names),
        "autonomy": autonomy,
        "max_tokens": max_tokens,
    }

    def _hold(reason: str, policy: dict | None = None) -> RouteDecision:
        return RouteDecision(model, model, reason, changed=False, kind="hold",
                             signals=signals, policy=policy or {})

    eligible, ineligible_reason, policy_meta = model_runtime_eligible(
        model, org_extra=org_extra, registry_entries=registry_entries
    )
    if not eligible:
        # Fail closed when org policy/registry explicitly blocks model.
        return RouteDecision(
            model, model, ineligible_reason, changed=False, kind="hold",
            signals=signals, policy={"eligible": False, **policy_meta},
        )

    if not is_routable(model):
        return _hold("model is not on the ladder — operator's choice respected", {"eligible": True, **policy_meta})

    policy_info = {"eligible": True, **policy_meta}
    # A count of zero means "the caller did not measure", not "this is a tiny
    # request". Treating a sentinel as a measurement is how a caller that forgot
    # to pass the context size ends up silently on the cheapest model.
    if context_tokens <= 0:
        return _hold("context size unknown — not routing on a sentinel", policy_info)

    idx = _tier_index(model)
    # Determine the minimum tier based on explicit min_tier or role mapping
    effective_min = min_tier if min_tier and is_routable(min_tier) else None
    if not effective_min and role:
        # Look up required tier for the role; may be None meaning no minimum
        role_min = ROLE_MIN_TIER.get(role)
        if role_min and is_routable(role_min):
            effective_min = role_min
    floor = _tier_index(effective_min) if effective_min else 0

    # Consequential tools pin the tier: a wrong answer here reaches a human.
    hit = tool_names & _CONSEQUENTIAL_TOOLS
    if hit:
        return _hold(f"consequential tool in use ({min(hit)})")

    # Draft mode means a human reads and edits the output before anyone sees
    # it, so a cheap draft costs nothing in quality.
    if (
        autonomy in ("ask", "ask_tools", "ask_all", "draft")
        and context_tokens <= CHEAP_CTX_TOKENS
        and not tool_names
    ):
        target = TIERS[floor]
        if _tier_index(target) < idx:
            return RouteDecision(
                target, target, "draft mode, no tools, short context",
                changed=True, kind="down", signals=signals, policy=policy_info,
            )
            return _hold("draft mode, but already at the cheapest allowed tier", policy_info)

    # Any tool use at all is multi-step reasoning, not a lookup. Leave it alone.
    if tool_names:
        return _hold(f"{len(tool_names)} tool(s) attached — multi-step", policy_info)

    # Long context: the cheap model starts losing the instruction before it
    # starts losing the facts.
    #
    # Note what is deliberately NOT a signal here: `max_tokens`. It is a cap on
    # generation, not a prediction of it, and billing is on tokens actually
    # emitted. An agent configured with the 4096 default that answers in 200
    # tokens pays for 200. Holding its tier on the cap would have made this
    # router a no-op for almost every agent in the fleet.
    if context_tokens > CHEAP_CTX_TOKENS:
        return _hold(f"context {context_tokens} tokens > {CHEAP_CTX_TOKENS}", policy_info)

    target = TIERS[floor]
    if _tier_index(target) >= idx:
        return _hold("already at or below the cheapest allowed tier", policy_info)

    return RouteDecision(
        target, target, "no tools, short context",
        changed=True, kind="down", signals=signals, policy=policy_info,
    )


def should_escalate(
    model: str | None,
    *,
    empty_response: bool = False,
    malformed_tool_call: bool = False,
    hit_iteration_limit: bool = False,
    max_tier: str | None = None,
) -> RouteDecision | None:
    """Return a stronger model when the run demonstrably failed, else None.

    This is the half that makes cheap routing safe. Every trigger is an
    observed failure, never a guess, so a run that succeeds on the cheap tier
    keeps the saving and a run that did not gets repaired instead of shipped.
    """
    if model is None:
        model = ""
    reasons = []
    if empty_response:
        reasons.append("empty response")
    if malformed_tool_call:
        reasons.append("malformed tool call")
    if hit_iteration_limit:
        reasons.append("iteration limit")
    if not reasons:
        return None

    if not is_routable(model):
        return RouteDecision(
            model, model,
            f"needs escalation ({', '.join(reasons)}) but the model is not on the ladder",
            changed=False, kind="up", signals={"reasons": reasons},
        )

    idx = _tier_index(model)
    ceiling = _tier_index(max_tier) if max_tier and is_routable(max_tier) else len(TIERS) - 1

    if idx >= ceiling:
        # Already the strongest we are allowed. Repairing is the caller's job;
        # silently picking an even bigger model would exceed the operator's cap.
        return RouteDecision(
            model, model, f"needs escalation ({', '.join(reasons)}) but already at cap",
            changed=False, kind="up", escalated_from=model,
            signals={"reasons": reasons},
        )

    target = TIERS[idx + 1]
    return RouteDecision(
        target, target, f"escalating: {', '.join(reasons)}",
        changed=True, kind="up", escalated_from=model, signals={"reasons": reasons},
    )


# ─── learned floor ────────────────────────────────────────────────────────
#
# An agent that keeps escalating has a capability problem, and rediscovering it
# on every run is pure waste: each rediscovery costs a cheap call, an
# escalation, and the failed answer. So the floor is remembered.
#
# Two rules keep this from becoming the stale weight table it was meant to
# avoid:
#
#   * it is stored under `extra_data`, never in `llm_config` — the operator's
#     configuration is not ours to rewrite, and a floor that silently changed
#     their model would be invisible to them;
#   * it expires. A floor learned against last month's tools and prompt is
#     worse than no floor, because it keeps a promotion alive that nothing
#     justifies any more.

FLOOR_TTL_S = 7 * 24 * 3600


def floor_from_extra(extra: dict | None) -> str | None:
    """The learned floor for this agent, if one is recorded and still fresh."""
    entry = (extra or {}).get("routing") or {}
    floor = entry.get("floor")
    at = entry.get("at")
    if not floor or not is_routable(floor):
        return None
    if not isinstance(at, (int, float, str)):
        return None
    try:
        age = time.time() - float(at)
    except (TypeError, ValueError):
        return None
    if age > FLOOR_TTL_S or age < -300:
        # negative age = clock skew; treat as unusable rather than eternal
        return None
    return floor


def remember_floor(extra: dict | None, model: str, reason: str) -> dict:
    """New `extra_data` dict carrying a recorded floor.

    Only ever moves the floor *up* the ladder and only for a routable model, so
    a stale or bogus record cannot demote an agent back to a cheap tier.
    """
    out = dict(extra or {})
    if not is_routable(model):
        return out
    prev = (out.get("routing") or {}).get("floor")
    if prev and is_routable(prev) and _tier_index(model) < _tier_index(prev):
        return out
    out["routing"] = {
        "floor": model,
        "at": time.time(),
        "reason": reason[:200],
    }
    return out


# Counters, so the saving is measured rather than asserted. Without these the
# only honest statement about fleet-wide cost is "it depends on the traffic
# mix", and nobody can act on that.
_stats: dict[str, int] = {}
_stats_lock = Lock()


def record(decision: RouteDecision) -> None:
    with _stats_lock:
        key = f"{decision.kind}:{decision.reason}"
        _stats[key] = _stats.get(key, 0) + 1


def stats() -> dict:
    """Routing counters.

    `down` over the total is the fraction of traffic that actually got cheaper,
    which is the only number worth quoting about cost. `up` is the price of the
    safety net: every run that had to be repaired cost both the cheap attempt
    and the repair, so it must not be counted as a saving.
    """
    with _stats_lock:
        out = dict(_stats)
    for prefix in ("down", "hold", "up"):
        out[f"{prefix}_total"] = sum(
            v for k, v in out.items() if k.startswith(f"{prefix}:")
        )
    return out
