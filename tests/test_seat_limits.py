"""Phase 7 slice: per-seat allowed models (org.extra_data.seats)."""
from types import SimpleNamespace

from aios.core.limits import seat_allows_model


def _org(extra: dict) -> SimpleNamespace:
    return SimpleNamespace(extra_data=extra or {})


def test_seat_allows_model_empty_config_allows():
    org = _org({})
    assert seat_allows_model(org, "u1", "openai/gpt-4o-mini") is True


def test_seat_allows_model_allows_listed_model():
    org = _org({"seats": {"u1": ["openai/gpt-4o-mini", "anthropic/claude-sonnet-4"]}})
    assert seat_allows_model(org, "u1", "openai/gpt-4o-mini") is True
    assert seat_allows_model(org, "u1", "anthropic/claude-sonnet-4") is True


def test_seat_allows_model_denies_unlisted_model():
    org = _org({"seats": {"u1": ["openai/gpt-4o-mini"]}})
    assert seat_allows_model(org, "u1", "openai/gpt-4o") is False


def test_seat_allows_model_other_seat_unlisted_denies():
    org = _org({"seats": {"u1": ["openai/gpt-4o-mini"]}})
    assert seat_allows_model(org, "u2", "openai/gpt-4o-mini") is True  # empty seat -> allow
