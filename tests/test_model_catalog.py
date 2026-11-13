"""Live OpenRouter catalog used by the agent model picker."""
from aios.dashboard.app import _catalog_models


def _model(model_id, *, prompt="0.000001", completion="0.000002", created=0,
           outputs=None, context=128000):
    return {
        "id": model_id,
        "name": model_id,
        "created": created,
        "context_length": context,
        "pricing": {"prompt": prompt, "completion": completion},
        "architecture": {"output_modalities": outputs or ["text"]},
    }


def test_catalog_keeps_chat_models_and_converts_price_per_million():
    rows = _catalog_models([_model("google/gemini-4-hydrogen", created=10)])
    assert rows == [{
        "model": "google/gemini-4-hydrogen",
        "name": "google/gemini-4-hydrogen",
        "input": 1.0,
        "output": 2.0,
        "context": 128000,
        "created": 10,
    }]


def test_catalog_excludes_batch_free_non_text_and_unpriced():
    rows = _catalog_models([
        _model("openai/gpt-5:batch"),
        _model("openai/gpt-5:free"),
        _model("black-forest/image-only", outputs=["image"]),
        _model("broken/no-price", prompt=None),
        _model("openai/gpt-5", created=5),
    ])
    assert [row["model"] for row in rows] == ["openai/gpt-5"]


def test_catalog_sorts_newest_first():
    rows = _catalog_models([
        _model("old/model", created=1),
        _model("new/model", created=99),
    ])
    assert [row["model"] for row in rows] == ["new/model", "old/model"]


def test_api_models_adds_direct_and_local_extras(monkeypatch):
    import asyncio
    import json

    from aios.dashboard import app as dashboard

    async def fake_catalog(force=False):
        return [_model("openai/gpt-5", created=1)]

    monkeypatch.setattr("aios.core.model_select.fetch_catalog", fake_catalog)
    response = asyncio.run(dashboard.api_models())
    ids = [row["model"] for row in json.loads(response.body)]
    assert "openai/gpt-5" in ids
    assert "ollama/llama3" in ids
    assert "openai-direct/gpt-4o" in ids
