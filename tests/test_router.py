"""The router must never be the reason a customer gets a worse answer.

Two properties carry the whole design, and both are asserted here rather than
assumed:

  * no signal is an accident — `route()` returns the configured model unless
    every signal says the work is small, so an unknown input degrades to "no
    change" rather than to a cheap model;
  * every saving is verified — `should_escalate()` fires on observed failure,
    so a run that needed the strong model gets it.

The cost arithmetic is checked against the price table in
`aios.core.tracing`, not against a made-up ratio, so a claim of "X% cheaper"
cannot drift away from what the code actually does.
"""

import pytest

from aios.core.router import CHEAP_CTX_TOKENS, TIERS, route, should_escalate
from aios.core.tracing import estimate_cost_detailed

FRONTIER = "openai/gpt-4o"
CHEAP = "openai/gpt-4o-mini"


def _tools(*names):
    return [{"type": "function", "function": {"name": n}} for n in names]


# ─── no-signal means no-change ────────────────────────────────────────────

def test_unknown_workload_is_left_alone():
    """Zero everything. The router has no idea what this is, so it must not
    guess — a router that guesses on missing input is a router that will
    eventually route real work to a model that cannot do it."""
    d = route(FRONTIER)
    assert d.model == FRONTIER
    assert d.changed is False


def test_unrecognised_model_is_never_routed_below():
    """An operator who configures a model this ladder has never heard of (a
    new frontier release, a fine-tune, a local model) must keep it."""
    for model in ("anthropic/claude-opus-4-20250514", "ollama/llama3", "openai/o3"):
        d = route(model, context_tokens=0, tools=None, autonomy="autonomous")
        assert d.model == model, f"{model} was downgraded to {d.model}"
        assert d.changed is False


def test_explicit_min_tier_is_respected():
    d = route(FRONTIER, context_tokens=10, min_tier=CHEAP, tools=None)
    assert d.model == CHEAP
    # a min_tier above the cheap rung floors the choice
    d = route(FRONTIER, context_tokens=10, min_tier=FRONTIER)
    assert d.model == FRONTIER
    assert d.changed is False


# ─── downgrade only when unambiguous ──────────────────────────────────────

def test_short_no_tool_request_drops_to_cheap():
    d = route(FRONTIER, context_tokens=500, tools=None, max_tokens=512)
    assert d.model == TIERS[0]
    assert d.changed is True


def test_any_tool_use_holds_the_tier():
    """Even a read-only tool. Tool use means the model has to decide what to
    call, read the result, and decide what that means — a three-step loop. That
    is not a lookup, and this is the case a naive length-based router gets
    wrong most often."""
    d = route(FRONTIER, context_tokens=500, tools=_tools("rag_search"), max_tokens=512)
    assert d.model == FRONTIER
    assert d.changed is False
    assert "multi-step" in d.reason


def test_consequential_tools_hold_the_tier_even_in_draft_mode():
    """The cheapest possible signal (draft, no context, short output) still
    must not route a mail-sending or SQL-writing tool to a small model."""
    for tool in ("send_email", "sql_query", "execute_code", "make_voice_call"):
        d = route(
            FRONTIER,
            context_tokens=10,
            tools=_tools(tool),
            autonomy="draft",
            max_tokens=256,
        )
        assert d.model == FRONTIER, f"{tool} was routed down to {d.model}"
        assert "consequential" in d.reason


def test_long_context_holds_the_tier():
    d = route(FRONTIER, context_tokens=CHEAP_CTX_TOKENS + 1, tools=None, max_tokens=512)
    assert d.model == FRONTIER


def test_max_tokens_is_not_a_gating_signal():
    """`max_tokens` is an output cap, not a prediction, and billing is on tokens
    actually emitted. Every agent configured with the 4096 default would have
    been held at the frontier model and the router would have saved nothing."""
    d = route(FRONTIER, context_tokens=10, tools=None, max_tokens=4096)
    assert d.changed is True
    assert d.model == TIERS[0]


def test_router_is_monotonic_downward_only():
    """Routing can only ever move toward cheaper, never past the configured
    model upward, and never below the floor."""
    for tokens in (0, 100, 3_999, 4_000, 50_000):
        d = route(FRONTIER, context_tokens=tokens, tools=None, max_tokens=512)
        assert TIERS.index(d.model) <= TIERS.index(FRONTIER)


# ─── escalation is what makes the saving safe ─────────────────────────────

def test_healthy_run_never_escalates():
    """The common case. If this returns a decision, the router is paying for a
    stronger model on every successful request and the saving is fictional."""
    assert should_escalate(TIERS[0]) is None
    assert should_escalate(TIERS[0], empty_response=False,
                           malformed_tool_call=False) is None


def test_observed_failures_escalate_one_step():
    cases = {
        "empty response": {"empty_response": True},
        "malformed tool call": {"malformed_tool_call": True},
        "iteration limit": {"hit_iteration_limit": True},
    }
    for reason, kwargs in cases.items():
        d = should_escalate(TIERS[0], **kwargs)
        assert d is not None, reason
        assert d.changed is True
        assert d.model == TIERS[1], reason
        assert reason in d.reason


def test_escalation_stops_at_the_configured_ceiling():
    """Silently picking a model stronger than the operator allows would spend
    money they explicitly capped. At the cap the caller gets told, not
    upgraded."""
    d = should_escalate(TIERS[1], empty_response=True, max_tier=TIERS[1])
    assert d is not None
    assert d.changed is False
    assert "cap" in d.reason


def test_escalation_stops_at_the_ladder_top():
    d = should_escalate(TIERS[-1], empty_response=True)
    assert d is not None
    assert d.changed is False
    assert "cap" in d.reason


def test_escalation_is_at_most_one_step_per_call():
    """One rung per observation. Jumping straight to the frontier on the first
    empty response throws away the entire saving on exactly the requests that
    were already struggling."""
    d = should_escalate(TIERS[0], empty_response=True, malformed_tool_call=True,
                        hit_iteration_limit=True)
    assert d.model == TIERS[1]


# ─── the saving is real arithmetic, not a ratio in a docstring ────────────

def test_cheap_tier_is_actually_cheaper_on_the_price_table():
    """Guard against the price table drifting out from under the router: if
    someone corrects gpt-4o-mini's price upward, this fails instead of the
    savings quietly becoming a lie."""
    frontier = estimate_cost_detailed(FRONTIER, 1_000, 500)
    cheap = estimate_cost_detailed(CHEAP, 1_000, 500)
    assert cheap < frontier
    assert frontier > 0


def test_cheapest_rung_is_the_cheapest_on_the_price_table():
    costs = [
        (m, estimate_cost_detailed(m, 1_000, 500))
        for m in TIERS
        if estimate_cost_detailed(m, 1_000, 500) > 0
    ]
    assert costs, "no tier has a price entry — the table lost these models"
    assert [c for _, c in costs] == sorted(c for _, c in costs), (
        f"TIERS is not ordered cheapest-first: {costs}"
    )


# ─── the wiring, not just the function ────────────────────────────────────

def test_agent_loop_routes_and_repairs():
    """The pure function passing is not enough — the run loop has to call it
    and act on the escalation, or the router is decoration."""
    import inspect

    from aios.core.agent import AgentRuntime

    # the loop is _run_stream_inner; run()/run_stream() only wrap it
    body = inspect.getsource(AgentRuntime._run_stream_inner)
    assert "route(" in body, "the run loop never routes"
    assert "should_escalate(" in body, "the run loop never escalates"

    repair_at = body.index("should_escalate(")
    assert "empty_response=True" in body[repair_at:repair_at + 200]

    # every escalation must be able to change the model, or it is a dead branch
    assert body.count("should_escalate(") == 2, "one escalation path is unreachable"
    assert "if repair and repair.changed:" in body


def test_configurable_tiers_flow_through_llm_config():
    """Operators need the escape hatches: `min_tier` to force quality and
    `max_tier` to cap spend."""
    import inspect

    from aios.core.agent import AgentRuntime

    src = inspect.getsource(AgentRuntime._run_stream_inner)
    assert 'llm_config.get("min_tier")' in src
    assert 'llm_config.get("max_tier")' in src


# ─── end-to-end through the run loop ──────────────────────────────────────

def _runtime(**llm_config):
    """An AgentRuntime with no tools and a stubbed LLM stream."""
    import types

    from aios.core.agent import AgentRuntime

    agent = types.SimpleNamespace(
        id="a1", org_id="o1", tools=[],
        llm_config={"model": FRONTIER, **llm_config},
        governance_config={}, name="t", system_prompt="hi",
        memory_config={}, extra_data={},
    )
    return AgentRuntime(agent)


def _fake_stream(rt, answers):
    """Replace the LLM stream with one that records the model it was called with.

    `answers` is consumed in order, so a single-element list models a run that
    never produces output and a two-element list models empty-then-good.
    """
    calls = []
    remaining = list(answers)

    async def _stream(*, messages, model, **kw):
        # an async generator function: the call site does
        # `async for ... in self._llm_chat_stream(...)`, so this must return an
        # async iterator directly rather than a coroutine wrapping one
        calls.append(model)
        content = remaining.pop(0) if remaining else "done"
        if content:
            yield {"type": "token", "content": content}
        yield {"type": "done"}

    rt._llm_chat_stream = _stream
    return calls


async def _drain(rt):
    events = []
    async for ev in rt.run_stream("c1", "hello"):
        events.append(ev)
    return events


@pytest.mark.asyncio
async def test_a_short_run_is_served_by_the_cheap_model():
    rt = _runtime()
    calls = _fake_stream(rt, ["hi there"])
    await _drain(rt)
    assert calls == [TIERS[0]], f"routed calls were {calls}"


@pytest.mark.asyncio
async def test_an_empty_cheap_response_is_repaired_by_escalation():
    """The whole safety claim, end to end: start cheap, detect the failure that
    actually happened, re-run on the next rung.

    The exact sequence matters. An earlier version routed on every iteration,
    so the second iteration saw "short context, no tools" again and put the run
    back on the cheapest rung: the calls came back [nano, nano] and the
    escalation bought a wasted call instead of a stronger model."""
    rt = _runtime()
    calls = _fake_stream(rt, ["", "recovered"])
    events = await _drain(rt)
    assert calls == [TIERS[0], TIERS[1]], f"calls were {calls}"
    assert any(ev.get("content") == "recovered" for ev in events)
    # the empty turn must never be shipped as the answer
    assert not any(
        ev.get("type") == "done" and ev.get("content") == "" for ev in events
    )


@pytest.mark.asyncio
async def test_a_successful_cheap_run_never_pays_for_the_escalation():
    rt = _runtime()
    calls = _fake_stream(rt, ["fine"])
    await _drain(rt)
    assert calls == [TIERS[0]], "a healthy run was charged for a second model"


@pytest.mark.asyncio
async def test_a_tool_using_agent_never_drops_to_the_cheap_model():
    rt = _runtime()
    rt.tool_engine.tools = ["rag_search"]
    rt.tool_engine.schemas = lambda: [
        {"type": "function", "function": {"name": "rag_search"}}
    ]
    calls = _fake_stream(rt, ["answer with a tool"])
    await _drain(rt)
    assert calls == [FRONTIER], f"a tool-using agent ran on {calls}"


@pytest.mark.asyncio
async def test_min_tier_forces_quality_back_on():
    """An operator who does not want the cheap rung must be able to say so."""
    rt = _runtime(min_tier=FRONTIER)
    calls = _fake_stream(rt, ["careful answer"])
    await _drain(rt)
    assert calls == [FRONTIER]


@pytest.mark.asyncio
async def test_max_tier_caps_the_escalation():
    rt = _runtime(max_tier=TIERS[0])
    calls = _fake_stream(rt, ["", "", ""])
    await _drain(rt)
    assert set(calls) == {TIERS[0]}, f"exceeded the configured cap: {calls}"


# ─── the counters must not flatter the number ─────────────────────────────

def test_direction_labels_separate_savings_from_repairs():
    """Both a downgrade and an escalation set `changed=True`. Counting them the
    same way put cost increases into the "money saved" counter, which is
    exactly the kind of error that makes a cost dashboard a lie."""
    from aios.core import router

    down = route(FRONTIER, context_tokens=10, tools=None)
    held = route(FRONTIER, context_tokens=10,
                 tools=[{"function": {"name": "send_email"}}])
    up = should_escalate(TIERS[0], empty_response=True)

    assert down.kind == "down"
    assert held.kind == "hold"
    assert up is not None and up.kind == "up"

    router._stats.clear()
    for d in (down, held, up):
        router.record(d)
    s = router.stats()
    assert s["down_total"] == 1
    assert s["hold_total"] == 1
    assert s["up_total"] == 1
    router._stats.clear()


def test_the_router_is_not_silent():
    """A router nobody can inspect is a router nobody can trust when spend goes
    up, so every decision carries a human-readable reason."""
    from aios.core.router import should_escalate as esc

    for d in (
        route(FRONTIER, context_tokens=10, tools=None),
        route(FRONTIER, context_tokens=10,
              tools=[{"function": {"name": "sql_query"}}]),
        esc(TIERS[0], empty_response=True),
    ):
        assert d is not None
        assert d.reason, "a decision with no reason cannot be audited"


# ─── gap: the learned floor must be durable, and must expire ──────────────

def test_floor_survives_a_restart_but_not_a_stale_week():
    """In-memory only, every worker and every restart rediscovered the same
    failure from scratch — a cheap call, an escalation and a wasted answer,
    repeatedly. The floor is persisted, and it expires so it cannot outlive the
    conditions that justified it."""
    import time as _t

    from aios.core.router import FLOOR_TTL_S, floor_from_extra, remember_floor

    extra = remember_floor({"project_path": "/srv/app"}, TIERS[1], "iteration limit")
    assert floor_from_extra(extra) == TIERS[1], "the floor did not survive a reload"
    # written alongside, not over, the tenant's own keys
    assert extra["project_path"] == "/srv/app"

    extra["routing"]["at"] = _t.time() - FLOOR_TTL_S - 1
    assert floor_from_extra(extra) is None, "a week-old floor is still being honoured"


def test_a_bogus_or_foreign_floor_is_ignored():
    """Records come from a JSON column, so they can be anything: a hand-edited
    row, a model this ladder does not know, or a timestamp from a broken clock.
    None of those may move an agent onto a model."""
    from aios.core.router import floor_from_extra

    assert floor_from_extra({"routing": {"floor": "anthropic/claude-opus-4", "at": 1e9}}) is None
    assert floor_from_extra({"routing": {"floor": TIERS[1]}}) is None, "no timestamp"
    assert floor_from_extra({"routing": {"floor": TIERS[1], "at": "soon"}}) is None
    assert floor_from_extra({"routing": {"floor": TIERS[1], "at": -1e12}}) is None
    assert floor_from_extra(None) is None
    assert floor_from_extra({}) is None


def test_a_recorded_floor_can_never_demote_an_agent():
    """Only promotion is a safety improvement. A floor that could lower the
    tier would hand back the exact silent-quality-loss the router avoids."""
    from aios.core.router import floor_from_extra, remember_floor

    start = {"routing": {"floor": TIERS[2], "at": __import__("time").time()}}
    kept = remember_floor(start, TIERS[0], "sloppy record")
    assert floor_from_extra(kept) == TIERS[2]


def _tool_burning_runtime():
    """An agent whose every turn requests a tool, so the iteration budget is
    what actually runs out. An empty *text* response does not reach that branch:
    it hits the empty-response repair instead, which deliberately does not
    persist a floor (one blank answer is usually a transient glitch, not a
    capability problem worth remembering for a week)."""
    # configured on a mid tier: that is the reachable case. An agent already
    # on the strongest tier which runs out of budget has nowhere to be promoted
    # to, so there is nothing to learn and nothing to record.
    rt = _runtime(model=TIERS[1])
    rt.tool_engine.tools = ["noop"]
    rt.tool_engine.schemas = lambda: [
        {"type": "function", "function": {"name": "noop"}}
    ]

    async def _execute(name, args):
        return "fine"

    rt.tool_engine.execute = _execute
    calls = []

    async def _stream(*, messages, model, **kw):
        calls.append(model)
        yield {
            "type": "tool_call",
            "tool_calls": [{
                "id": f"c{len(calls)}",
                "function": {"name": "noop", "arguments": "{}"},
            }],
        }
        yield {"type": "done"}

    rt._llm_chat_stream = _stream
    return rt, calls


@pytest.mark.asyncio
async def test_an_exhausted_run_leaves_a_durable_floor():
    """The gap: the floor was in-memory only, so every worker and every restart
    rediscovered the same failure — a cheap call, an escalation and a wasted
    answer, repeated forever."""
    from aios.core.router import floor_from_extra

    rt, _ = _tool_burning_runtime()
    await _drain(rt)
    assert floor_from_extra(rt.agent.extra_data) == TIERS[2], (
        "the next run would rediscover this failure from scratch"
    )


@pytest.mark.asyncio
async def test_an_agent_already_on_the_strongest_tier_learns_nothing():
    """Ran out of budget on the top tier: there is no stronger model, so
    recording a floor would be a fiction."""
    from aios.core.router import floor_from_extra

    rt, _ = _tool_burning_runtime()
    rt.agent.llm_config["model"] = TIERS[-1]
    await _drain(rt)
    assert floor_from_extra(rt.agent.extra_data) is None


@pytest.mark.asyncio
async def test_one_blank_answer_does_not_become_a_permanent_promotion():
    """A transient empty response must not pin an agent to a pricier model for a
    week. Only an exhausted iteration budget is treated as a capability
    problem."""
    from aios.core.router import floor_from_extra

    rt = _runtime()
    _fake_stream(rt, [""])
    await _drain(rt)
    assert floor_from_extra(rt.agent.extra_data) is None


@pytest.mark.asyncio
async def test_the_learned_floor_applies_to_the_next_run():
    """End to end: run one exhausts its budget, and the following run starts on
    the stronger tier without paying to discover the failure again."""
    from aios.core.router import remember_floor

    rt = _runtime()
    rt.agent.extra_data = remember_floor(
        rt.agent.extra_data, TIERS[1], "iteration limit"
    )
    calls = _fake_stream(rt, ["answered on a stronger tier"])
    await _drain(rt)
    assert calls == [TIERS[1]], f"the learned floor was ignored: {calls}"


@pytest.mark.asyncio
async def test_an_operators_min_tier_still_wins_over_the_learned_one():
    """The floor is a fallback, not an override."""
    from aios.core.router import remember_floor

    rt = _runtime(min_tier=TIERS[2])
    rt.agent.extra_data = remember_floor(rt.agent.extra_data, TIERS[1], "iteration limit")
    calls = _fake_stream(rt, ["answered"])
    await _drain(rt)
    assert calls == [TIERS[2], TIERS[2]] or calls == [TIERS[2]], f"min_tier lost: {calls}"


# ─── gap: tool results were re-sent at full size on every iteration ───────

def test_tool_results_are_trimmed_but_never_removed():
    """A tool result goes into the live context at full size and is re-sent on
    every later iteration. Trimming is the saving; deleting the message is not
    an option, because a `role="tool"` message must follow an assistant message
    carrying the matching `tool_call_id` or the provider rejects the request."""
    from aios.core.agent import _TOOL_RESULT_CAP_CHARS, _trim_tool_results

    big = "x" * 50_000
    ctx = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "function": {}}]},
        {"role": "tool", "tool_call_id": "1", "content": big},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "2", "function": {}}]},
        {"role": "tool", "tool_call_id": "2", "content": big},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "3", "function": {}}]},
        {"role": "tool", "tool_call_id": "3", "content": big},
    ]
    before = sum(len(m["content"]) for m in ctx if m.get("role") == "tool")
    _trim_tool_results(ctx)
    after = sum(len(m["content"]) for m in ctx if m.get("role") == "tool")

    # the chain is intact
    assert len(ctx) == 6
    assert [m["role"] for m in ctx] == ["assistant", "tool"] * 3
    assert [m.get("tool_call_id") for m in ctx if m["role"] == "tool"] == ["1", "2", "3"]
    # the most recent results are untouched — those are the ones in play
    assert ctx[-1]["content"] == big
    assert ctx[3]["content"] == big
    # and the stale one was actually cut
    assert before > after
    assert len(ctx[1]["content"]) <= _TOOL_RESULT_CAP_CHARS + 60


def test_trimming_reports_how_much_it_dropped():
    """A silent truncation reads as a complete result, which is how a model
    ends up reasoning over data that is not there."""
    from aios.core.agent import _trim_tool_results

    # needs three tool results: the two most recent are kept whole by design
    ctx = [
        {"role": "assistant", "tool_calls": [{"id": "1", "function": {}}]},
        {"role": "tool", "tool_call_id": "1", "content": "y" * 10_000},
        {"role": "assistant", "tool_calls": [{"id": "2", "function": {}}]},
        {"role": "tool", "tool_call_id": "2", "content": "z"},
        {"role": "assistant", "tool_calls": [{"id": "3", "function": {}}]},
        {"role": "tool", "tool_call_id": "3", "content": "z"},
    ]
    _trim_tool_results(ctx)
    assert "trimmed" in ctx[1]["content"]
    assert "6000 chars trimmed" in ctx[1]["content"]
    assert ctx[3]["content"] == "z" and ctx[5]["content"] == "z"


def test_trimming_leaves_short_results_alone():
    from aios.core.agent import _trim_tool_results

    ctx = [
        {"role": "assistant", "tool_calls": [{"id": str(i), "function": {}}]}
        for i in range(3)
    ]
    ctx = [m for pair in zip(ctx, [{"role": "tool", "tool_call_id": str(i),
                                    "content": "small result"} for i in range(3)])
           for m in pair]
    before = [dict(m) for m in ctx]
    _trim_tool_results(ctx)
    assert ctx == before, "short results were mangled"
