---
name: perf-audit
description: Quick performance audit — N+1, god nodes, cache, worker lag, and bundle size. Use when app feels slow, before scaling, or reviewing hot paths.
---

# Perf Audit

Measure first, fix smallest.

## 5-minute sweep

1. **Graphify god nodes**: `graphify query "slow path"` → hub with >50 edges → split.
2. **DB**: grep `select.*where` loops → N+1? Add `selectinload`/batch. Check PC `aios/core/limits.py:check_org_limits` not called per row.
3. **Cache**: hot `GET /health` or `get_context` → `lru_cache` or Redis TTL. Already have `LRU cache with TTL` community hub.
4. **Workers**: `arq` queue lag → `redis-cli LLEN arq:queue` or `WorkerSettings.redis_settings`. Retry only 5xx, not 4xx.
5. **Frontend**: `website/index.html` bundle → no new lib for date picker / chart if native/CSS can do it.

## Fix ladder (ponytail)

- One line: `@lru_cache(maxsize=1000)` on fetch.
- Next: Redis `SET key value EX 300`.
- Only then: new worker, new cache service.

## Checklist

- [ ] Every list endpoint `LIMIT 10` default (already `agents` limit 10 in `get_context`)
- [ ] `httpx.AsyncClient` reused via pool, not per-request new (but `send_event` uses context manager with 5s timeout — OK for low volume, pool if hot)
- [ ] `time.time()` skew handling not in tight loop
- [ ] `ponytail:` comment on ceilings (`global lock`, `O(n²) scan`)

## Don't

- Premature sharding, micro-optimizing cold paths.
- Adding Redis Streams before HTTP outbox proves insufficient (spec G3 decision already: HTTP first).
