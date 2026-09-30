# ratelimit.py +2

> 6 nodes · cohesion 0.33

## Key Concepts

- **ratelimit.py** (8 connections) — `aios/api/ratelimit.py`
- **_get_org_key()** (2 connections) — `aios/api/ratelimit.py`
- **Rate limiting configuration using slowapi. Usage: from aios.api.ratelimit…** (1 connections) — `aios/api/ratelimit.py`
- **Extract org_id from JWT for per-tenant rate limiting. Falls back to IP.** (1 connections) — `aios/api/ratelimit.py`
- **slowapi** (1 connections)
- **slowapi_util** (1 connections)

## Relationships

- [Auth Token Factory](Auth_Token_Factory.md) (1 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (1 shared connections)
- [Settings & Channel Health](Settings_&_Channel_Health.md) (1 shared connections)
- [Cron Scheduler & Durable Guard](Cron_Scheduler_&_Durable_Guard.md) (1 shared connections)

## Source Files

- `aios/api/ratelimit.py`

## Audit Trail

- EXTRACTED: 9 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*