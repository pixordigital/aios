"""Tests for rate-limit hardening — Redis-down fallback behavior.

slowapi's in-memory fallback keeps limits enforced (within a per-process
budget) when Redis is unreachable, instead of the raw ConnectionError
bubbling to a fail-open 200 or 500. The middleware itself only registers in
prod (not debug), so tests target limiter construction.
"""

import importlib

from aios.config import settings


def test_redis_limiter_has_in_memory_fallback(monkeypatch):
    """When redis_url set, the Limiter is built with in_memory_fallback_enabled."""
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(settings, "debug", False)

    import aios.api.ratelimit as rl
    importlib.reload(rl)

    assert rl._storage_uri == "redis://localhost:6379/0"
    assert rl.limiter._in_memory_fallback_enabled is True
    assert rl.limiter._fallback_storage is not None


def test_memory_limiter_when_no_redis(monkeypatch):
    """Without redis_url, limiter stays memory-backed (no fallback needed)."""
    monkeypatch.setattr(settings, "redis_url", "")

    import aios.api.ratelimit as rl
    importlib.reload(rl)

    assert rl._storage_uri is None
    assert rl.limiter._storage_uri is None  # memory:// default
    assert rl.limiter._in_memory_fallback_enabled is False
