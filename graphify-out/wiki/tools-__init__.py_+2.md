# tools/__init__.py +2

> 8 nodes · cohesion 0.25

## Key Concepts

- **test_ratelimit.py** (5 connections) — `tests/test_ratelimit.py`
- **importlib** (4 connections)
- **test_memory_limiter_when_no_redis()** (2 connections) — `tests/test_ratelimit.py`
- **test_redis_limiter_has_in_memory_fallback()** (2 connections) — `tests/test_ratelimit.py`
- **tools/__init__.py** (1 connections) — `aios/tools/__init__.py`
- **Tests for rate-limit hardening — Redis-down fallback behavior. slowapi's in-…** (1 connections) — `tests/test_ratelimit.py`
- **When redis_url set, the Limiter is built with in_memory_fallback_enabled.** (1 connections) — `tests/test_ratelimit.py`
- **Without redis_url, limiter stays memory-backed (no fallback needed).** (1 connections) — `tests/test_ratelimit.py`

## Relationships

- [Agent Runtime Loop](Agent_Runtime_Loop.md) (1 shared connections)
- [SDK Teams API](SDK_Teams_API.md) (1 shared connections)
- [Settings & Channel Health](Settings_&_Channel_Health.md) (1 shared connections)

## Source Files

- `aios/tools/__init__.py`
- `tests/test_ratelimit.py`

## Audit Trail

- EXTRACTED: 10 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*