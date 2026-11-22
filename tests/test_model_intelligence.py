"""Model intelligence: least-cost eligible selection and evidence-backed proposals."""

from aios.governance.model_intelligence import (
    ModelRegistryEntry,
    cost_per_successful_task,
    eligible_models,
    recommend_change,
    rollback_target,
    select_model,
)


def _m(key, *, tier=1, quality=0.9, reliability=1.0, inp=1.0, out=2.0, approved=True, **kw):
    data = dict(
        price_currency="USD",
        privacy_ok=True,
        contract_ok=True,
        latency_p95_ms=0,
        capabilities=["text"],
        context_window=200000,
    )
    data.update(kw)
    return ModelRegistryEntry(
        org_id="o", model_key=key, provider="p", tier=tier, quality_score=quality,
        reliability=reliability, input_price_per_1m=inp, output_price_per_1m=out,
        approved=approved, **data,
    )


def test_cost_per_success_accounts_for_reliability():
    cheap = _m("cheap", inp=1, out=1, reliability=0.5)
    dear = _m("dear", inp=2, out=2, reliability=1.0)
    work = {"avg_input_tokens": 1_000, "avg_output_tokens": 1_000}
    assert cost_per_successful_task(cheap, **work) == cost_per_successful_task(dear, **work)
    # zero reliability is infinite cost per success
    assert cost_per_successful_task(_m("dead", reliability=0), **work) == float("inf")


def test_unapproved_and_ineligible_models_are_filtered():
    entries = [
        _m("draft", approved=False),
        _m("bad_privacy", privacy_ok=False),
        _m("slow", latency_p95_ms=9000),
        _m("good"),
    ]
    eligible = eligible_models(entries, max_latency_p95_ms=2000, privacy_required=True)
    assert [e.model_key for e in eligible] == ["good"]


def test_required_capabilities_and_tier():
    entries = [_m("text"), _m("vision", capabilities=["text", "vision"], tier=2)]
    assert [e.model_key for e in eligible_models(entries, required_capabilities=("vision",))] == ["vision"]
    assert [e.model_key for e in eligible_models(entries, tier=1)] == ["text"]


def test_select_least_cost_per_success():
    entries = [
        _m("small", inp=0.5, out=0.5, quality=0.8),
        _m("mid", inp=1, out=1, quality=0.95),
        _m("big", inp=5, out=5, quality=0.99),
    ]
    chosen, cost = select_model(
        entries, avg_input_tokens=10_000, avg_output_tokens=2_000, min_quality=0.9
    )
    assert chosen.model_key == "mid"
    assert cost > 0


def test_select_returns_none_when_nothing_eligible():
    chosen, cost = select_model([_m("x", quality=0.2)], avg_input_tokens=1, avg_output_tokens=1, min_quality=0.9)
    assert chosen is None
    assert cost == float("inf")


def test_recommend_change_requires_approval_and_evidence():
    cur = _m("cur", inp=3, out=3)
    prop = _m("prop", inp=1, out=1)
    rec = recommend_change(cur, prop, avg_input_tokens=10_000, avg_output_tokens=1_000, monthly_tasks=1000)
    assert rec["recommended"] is True
    assert rec["requires_founder_approval"] is True
    assert rec["expected_monthly_savings"] > 0
    assert rec["uncertainty"]


def test_recommend_rejects_quality_regression_and_unapproved():
    cur = _m("cur", quality=0.95)
    prop = _m("prop", quality=0.7, inp=0.1, out=0.1)
    assert recommend_change(cur, prop, avg_input_tokens=1, avg_output_tokens=1, monthly_tasks=1, required_quality=0.9)["recommended"] is False
    draft = _m("draft", approved=False)
    assert recommend_change(cur, draft, avg_input_tokens=1, avg_output_tokens=1, monthly_tasks=1)["recommended"] is False


def test_rollback_only_to_approved_previous():
    entries = [_m("a"), _m("b", approved=False)]
    assert rollback_target(entries, agent_default_key="a", previous_key="b") == "a"
    assert rollback_target(entries, agent_default_key="c", previous_key="a") == "a"
