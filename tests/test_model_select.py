"""Model selection is a recommendation, so its rules must be testable offline."""

from aios.core.model_select import profile_for, rank


def _model(mid, pin, pout, *, ctx=200_000, intel=None, coding=None, agentic=None,
           params=("tools", "structured_outputs")):
    return {
        "id": mid,
        "context_length": ctx,
        "pricing": {"prompt": str(pin / 1e6), "completion": str(pout / 1e6)},
        "architecture": {"output_modalities": ["text"]},
        "supported_parameters": list(params),
        "benchmarks": {"artificial_analysis": {
            "intelligence_index": intel, "coding_index": coding, "agentic_index": agentic,
        }},
    }


def test_cheapest_wins_when_quality_is_equal():
    pool = [
        _model("a/expensive", 10, 50, intel=40, agentic=40),
        _model("b/cheap", 1, 5, intel=40, agentic=40),
    ]
    assert rank("manager", pool)[0].model == "b/cheap"


def test_unmeasured_primary_axis_is_not_recommended():
    """Manager's primary axis is intelligence; no benchmark means no claim."""
    pool = [
        _model("a/blind", 0.1, 0.2, agentic=99),
        _model("b/measured", 5, 20, intel=50, agentic=50),
    ]
    assert [p.model for p in rank("manager", pool)] == ["b/measured"]


def test_batch_free_and_tool_less_models_are_not_candidates():
    pool = [
        _model("a/batch:batch", 0.1, 0.2, intel=50, agentic=50),
        _model("b/free:free", 0, 0, intel=50, agentic=50),
        _model("c/chat", 0.1, 0.2, intel=50, agentic=50, params=("structured_outputs",)),
        _model("d/ok", 1, 5, intel=50, agentic=50),
    ]
    profile = profile_for("manager")
    assert profile["tools"] is True
    assert [p.model for p in rank("manager", pool)] == ["d/ok"]
