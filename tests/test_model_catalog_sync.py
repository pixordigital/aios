"""Diff and apply rules for the watched model catalog."""
from aios.core.model_catalog_sync import apply_updates, diff_catalog


def _row(model_id, *, created, prompt, completion, canonical_slug=None):
    return {
        "id": model_id,
        "canonical_slug": canonical_slug or model_id,
        "created": created,
        "pricing": {"prompt": prompt, "completion": completion},
    }


def test_price_changed_reported_and_refreshed():
    watched = {"openai/gpt-4o": (2.50, 10.00)}
    catalog = [_row("openai/gpt-4o", created=10, prompt="0.000003", completion="0.000011")]
    diff = diff_catalog(catalog, watched)
    assert [item["id"] for item in diff["price_changed"]] == ["openai/gpt-4o"]
    assert diff["price_changed"][0]["old"] == (2.50, 10.00)
    assert diff["price_changed"][0]["new"] == (3.0, 11.0)
    updated = apply_updates(watched, diff)
    assert updated["openai/gpt-4o"] == (3.0, 11.0)


def test_missing_id_gains_newer_same_family_successor_and_keeps_old_key():
    old = "anthropic/claude-sonnet-4-20250514"
    new = "anthropic/claude-sonnet-4.6"
    watched = {old: (3.0, 15.0)}
    catalog = [_row(new, created=200, prompt="0.000003", completion="0.000015")]
    diff = diff_catalog(catalog, watched)
    assert diff["missing"] == [old]
    assert [item["id"] for item in diff["successor_candidates"]] == [new]
    updated = apply_updates(watched, diff)
    assert old in updated
    assert updated[new] == (3.0, 15.0)


def test_cross_family_successor_is_rejected():
    old = "anthropic/claude-sonnet-4-20250514"
    other = "anthropic/claude-opus-4.6"
    watched = {old: (3.0, 15.0)}
    catalog = [_row(other, created=300, prompt="0.000003", completion="0.000015")]
    diff = diff_catalog(catalog, watched)
    assert diff["successor_candidates"] == []
    updated = apply_updates(watched, diff)
    assert other not in updated
    assert updated[old] == (3.0, 15.0)


def test_batch_and_free_variants_are_ignored():
    watched = {"openai/gpt-4o": (2.50, 10.00)}
    catalog = [
        _row("openai/gpt-4o:batch", created=900, prompt="0.000001", completion="0.000002"),
        _row("openai/gpt-4o:free", created=800, prompt="0", completion="0"),
    ]
    diff = diff_catalog(catalog, watched)
    assert diff["price_changed"] == []
    assert diff["successor_candidates"] == []
    updated = apply_updates(watched, diff)
    assert updated == watched
    assert not any(key.endswith((":batch", ":free")) for key in updated)
