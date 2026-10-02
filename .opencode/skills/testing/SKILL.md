---
name: testing
description: Minimal viable testing — one runnable check per behavior, ASGI over mocks, real DB constraints. Use when adding tests or verifying non-trivial logic (branch/loop/parser/money/security).
---

# Testing (ponytail-aligned)

Smallest thing that fails if logic breaks.

## Rule

- Trivial one-liner → no test (YAGNI).
- Non-trivial (branch, loop, parser, money, security) → ONE runnable check: `assert`-based `demo()`/`__main__` or one `test_*.py`. No fixtures/frames unless asked.

## How in this repo

- **AIOS**: `tests/conftest.py` SQLite `tests/test.db` + `httpx ASGITransport`. Pytest `asyncio_mode=auto`, `pythonpath="."`.
- **ARVO**: `tests/test_api.py` `TestClient` + `tests/test_aios_integration.py`.
- **Pattern**: reuse existing `test_arvo_integration.py` / `test_aios_integration.py` — sign/verify roundtrip + replay + health 401 + events idempotency.

## Template

```python
def test_feature():
    _clear_nonces(); _clear_events()
    hdr = sign_request("POST", "/api/...", body, "kid", "key")
    assert verify_request(..., hdr["X-Service-Signature"], "key")
    # via TestClient with real app
    c = TestClient(app)
    r = c.post(path, content=body, headers={**hdr, "Idempotency-Key": "idem-1"})
    assert r.status_code == 200 and r.json()["deduplicated"] is False
```

## Must-check

- Auth: happy + wrong key + stale timestamp + tampered body + replay.
- Idempotency: first `deduplicated:False`, second `True`.
- DB constraint: duplicate insert → 409 or handled, not 500.

## Don't

- Mock what you can run: prefer `TestClient`/real SQLite over mock redis/db.
- Per-function suites. One file, ~5 cases, done.
