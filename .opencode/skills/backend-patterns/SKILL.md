---
name: backend-patterns
description: Backend architecture patterns — layered vs modular, data modeling, queue/worker, caching, and failure modes. Use when designing APIs, workers, data flows, or reviewing backend complexity.
---

# Backend Patterns

Minimal backend that survives 3am.

## Ladder (reuse ponytail)

1. Does it need to exist? No → skip.
2. Already in codebase? Reuse it.
3. Stdlib/platform does it? Use it.
4. New dep? Only if 5 lines can't.

## Patterns

- **Layering**: `api → service → repo → db`. No service with 1 method → inline. No repo abstraction over single query → use query directly.
- **Data**: FK + constraint > app check. Transaction at service boundary, not per query. Idempotency key on every side-effect (already in `aios/integrations/*`).
- **Workers (ARQ)**: `tasks/queue.py` pool + `tasks/worker.py` functions. Retry only 5xx/429/timeout, not 4xx. Backoff `0.5 * 2^attempt`.
- **Cache**: `lru_cache` or Redis TTL. No custom cache class until `lru_cache` measurably fails. Key = `org_id:resource:id`.
- **Config**: `BaseSettings` with `AIOS_`/`ARVO_` prefix. Feature flag `enabled=False` default. No behavior change when off.

## Anti-patterns → fix

- God service / god node (graphify `god nodes`) → split by community.
- N+1 query → `selectinload`/`joinedload` or batch `WHERE id IN (...)`.
- Sync call in request path that can be async → enqueue job (G13 fast path: WhatsApp `process_inbound` never calls ARVO sync).
- New abstraction with 1 impl → delete interface, keep concrete.

## Check

- Every write path has idempotency or unique constraint.
- Every external call has timeout (5s) + retry (3×) + circuit fallback.
- `ponytail:` comment on deliberate simplifications (global lock, O(n²) scan).
