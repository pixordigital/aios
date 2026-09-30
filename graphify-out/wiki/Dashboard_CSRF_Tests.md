# Dashboard CSRF Tests

> 12 nodes · cohesion 0.18

## Key Concepts

- **.test_cross_origin_rejected()** (4 connections) — `tests/test_security.py`
- **AsyncClient** (3 connections)
- **TestDashboardCSRF** (3 connections) — `tests/test_security.py`
- **TestUnauthenticatedEndpoints** (3 connections) — `tests/test_security.py`
- **.test_requires_auth()** (3 connections) — `tests/test_security.py`
- **TestWebhookFailClosed** (3 connections) — `tests/test_security.py`
- **parametrize** (2 connections)
- **.test_evolution_missing_signature()** (2 connections) — `tests/test_security.py`
- **Dashboard state-changing routes must reject cross-origin requests.** (1 connections) — `tests/test_security.py`
- **Authenticated request with a foreign Referer must be rejected (403).** (1 connections) — `tests/test_security.py`
- **Webhooks must reject requests with missing signatures.** (1 connections) — `tests/test_security.py`
- **Previously-unauthenticated endpoints must now require auth.** (1 connections) — `tests/test_security.py`

## Relationships

- [Outbound Message & Discord Channel](Outbound_Message_&_Discord_Channel.md) (3 shared connections)

## Source Files

- `tests/test_security.py`

## Audit Trail

- EXTRACTED: 15 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*