# Pending work

Last updated: 2026-11-17

## Open

- Customer viability browser simulation (2026-11-17): two isolated Persona
  Product Tester prospect sessions are complete. Results are in
  `product-feedback/2026-11-17/panel-summary.md`, individual reports and
  screenshots. Both new-business prospects were blocked from starting an
  evaluation; the CTA scrolls to product information, the dashboard login says
  signups are closed, and the public copy also says internal/self-hosted.
  External market viability and authenticated product workflows remain
  untested. A dedicated non-production account is still needed to test internal
  owner/sales/operations workflows. The operations buyer persona is prepared in
  `product-feedback/2026-11-17/persona-operations-buyer.yaml` but was not run.
  Resume by reading the installed Persona Product Tester skill, then use an
  isolated agent-browser session at `http://127.0.0.1:8777/dashboard` with the
  provided test account. Keep actions within that non-production account; do
  not reopen signup. Chromium is installed; this host requires
  `agent-browser --args "--no-sandbox"` to start.

- Internal-tool pivot (2026-11-17): billing and multi-tenant signup are disabled
  by commenting their entrypoints (see `## Done` for the exact list). Do not
  re-enable either without a paying tenant and end-to-end lifecycle tests.
- Activate the fleet: `AIOS_OPENROUTER_API_KEY` is still empty in production, so
  all 12 operational agents remain `draft` and no event dispatch reaches them.
  (`red-manager` is archived: 13 rows, 12 operational.) Set the key in Coolify,
  redeploy, then run the deploy/probe for each agent.
- Telegram channel `agents-test-telegram-s9` still has an empty bot token and no
  agent/team assignment.
- Uncommitted (2026-11-17): approvals dashboard, ICM contract viewer, unit-cost
  endpoint + analytics card, outcomes baseline/delta, `tests/test_paid_workflow_e2e.py`.
  Nothing deployed. Commit/push only on operator request; then redeploy and
  verify `/dashboard/approvals` and `/dashboard/contracts` render in the container.


## Open — stateless migration

Goal: API tier stateless, deployable without Docker, multi-node capable.
Non-negotiables: no behavior change until `AIOS_RUNTIME_ROLE` is set explicitly;
every phase reversible; `pendingwork.md` updated at each gate.
Do not re-litigate: role split before scheduler move; vectors last; Redis stays
(load-bearing for queue, streams, leases, pub/sub).
Baseline: full suite green 2026-11-15 with Phases 1/2/3/5 merged:
1425 passed, 11 skipped in 13:37 (`pytest -n 4 --dist loadfile`).
Historical failures fixed 2026-11-15: `test_config.py::test_health_endpoints`
(module-level TestClient never ran lifespan, so `registry.active` was None) and
`test_agent_canvas_events.py::test_autonomous_run_stream_emits_trial_and_tokens`
`_StubAgent` lacked `extra_data` for ICM binding).

Deploy executed: production deployment ran 2026-11-16T22:20:37Z on commit `a2ee3de` (Phases 0-8).
Postgres is at alembic head `c2d3e4f5a6b7`. App and worker containers healthy, `/health/ready` returns 200.

### Phase 0 — bare-metal deploy scaffolding  [x] done 2026-11-15
- `deploy/aios-migrate.service`: oneshot `alembic upgrade head`, `RemainAfterExit`.
- `deploy/aios-server.service`: rewritten. `EnvironmentFile=/etc/aios/aios.env`,
  `After=`/`Requires=aios-migrate`, bind `127.0.0.1:8777`, journal logs,
  `StateDirectory=aios`, `AIOS_RUNTIME_ROLE=api` (ignored until Phase 1).
- `deploy/aios-worker.service`: `aios-worker` console script, role=worker.
- `deploy/aios-gateway.service`: role=gateway on `127.0.0.1:8778`. Until Phase 1
  it behaves like a second API process; do not enable it yet.
- `deploy/aios-backup.service` + `.timer`: 03:30 daily, backup dir
  `/var/lib/aios/backups`, `Persistent=true`.
- `pyproject.toml`: `aios-worker` script pointed at `main`. `worker.run` is now
  a sync alias, so console scripts installed before the fix also work; the old
  `async def run` was called without `await` and exited immediately.
- `DEPLOY.md`: "Bare metal (systemd)" section with install steps.
Gate: `systemd-analyze verify` reports no syntax errors. Current warnings are
only missing `/opt/aios` binaries on this dev host; unit syntax is clean.
Not yet exercised on a real VM.

### Phase 1 — runtime role split  [x] done 2026-11-15
- `aios/config.py`: `runtime_role: str = "all"` plus `runtime_role()`,
  `runs_channels()`, `runs_cron()`, `runs_telemetry_flush()`,
  `channels_are_remote()`. Roles: `all|api|worker|gateway`.
- `aios/main.py`: invalid role refuses to boot; startup log reports role and
  enabled subsystems. Channels, cron, telemetry flush and WhatsApp restore are
  guarded by role. `/health/ready` reports `role`.
- `aios/core/whatsapp_guard.py`: `restore_all_orgs()` extracted; called from
  `main.py` and from `WorkerSettings.on_startup`, so the worker process also
  knows opt-outs and cooldowns (delivery runs there).
- `aios/tasks/jobs.py`: `channel_sync_job` + registration. API replicas enqueue
  it instead of calling `channel_mgr` directly.
- `aios/api/channels.py`, `aios/dashboard/app.py`: in `api` role the toggle,
  start, save and delete paths enqueue the job. Delete now stops the adapter.
- `aios/channels/manager.py`: `stop_by_id()` so a deleted row can still stop a
  live poller.
- `tests/test_runtime_role.py`: 7 passed (role matrix, api enqueues, all local).
- Gate: subset 49 passed. Both historical test failures are fixed:
  `test_health_endpoints` (backend now initialized by `test_db_session`) and the
  canvas stub (`extra_data = {}`).
- Compose left unchanged (role unset = `all`). Enable the split only with the
  gateway unit running; never set `AIOS_RUNTIME_ROLE=api` without a gateway.

### Phase 2 — scheduler out of API  [x] done 2026-11-15

- `aios/core/cron_scheduler.py`: `run_once()` replaces the `_loop()` task.
  Postgres takes the advisory lock per tick (skipped on SQLite, which is
  single-process); the loser returns without touching anything. `_backup_tick`
  stays in the pass — compose deployments have no systemd backup timer.
- `aios/tasks/worker.py`: `cron_tick_job` runs `run_once()` every minute;
  `telemetry_flush_job` flushes the worker's own in-memory metrics every 5 min
  (the API loop never saw worker-process agent runs, in any role).
- `aios/main.py`: lifespan no longer starts/stops the cron scheduler; startup
  log now reports `cron=worker`.
- `tests/test_cron_worker.py`: registration, scheduling, SQLite `run_once()`.

Known limit: the lock is per tick, not per process, so the in-memory
`_last_*_day` guards reset when the winning worker changes and a daily sweep can
repeat in another process. DB idempotency keys (`sales-drop:<org>:<date>`,
`crm-stalled:<deal>:<date>`) cap the effect. Fix only if duplicates show up in
practice: move the daily guard into a table.

### Phase 3 — connection pool math  [x] done 2026-11-15

`PRODUCTION_CONFIG.md` "Connection budget": per-process
`AIOS_DB_POOL_SIZE + AIOS_DB_MAX_OVERFLOW` (default 5 + 5) × (API + worker +
gateway replicas) must stay under Postgres `max_connections`. Compose sets
`max_connections=60`, i.e. at most six database-facing processes at defaults.

### Phase 4 — vectors to Postgres  [x] done 2026-11-16

- `aios/core/vector_store.py`: pgvector store (`memory_vectors`, 384 dims,
  org+agent scoped) with the same five operations the SQLite store exposes
  (store, similarity, FTS, SA-CTS, RL update/discard). Selected by
  `AIOS_VECTOR_BACKEND=auto|postgres|sqlite`; `auto` follows the engine dialect,
  so SQLite dev keeps `data/vectors/*.db` unchanged.
- `alembic/versions/c2d3e4f5a6b7_add_memory_vectors.py`: table, generated
  `content_tsv`, GIN index, HNSW cosine index. Skipped on non-Postgres binds.
- `aios/core/memory.py`: `MemoryManager` delegates to the store and resolves the
  agent's org once (the table is org-scoped).
- `aios/core/rag.py`: agent-scoped `hybrid_search` reads through
  `MemoryManager.search_similar`, so it sees the same store. `/health` now
  reports `hnsw` from the real index instead of hardcoded False.
- `scripts/migrate_vectors_to_pg.py`: idempotent copy of the old per-agent
  files, original ids preserved; `--dry-run` supported.
- `tests/test_vector_store.py`: backend switch, dialect auto-detect, SQLite
  isolation, embedding literal validation.
- Verified against a scratch Postgres 15 + pgvector database, with the full
  Alembic chain: write, similarity, FTS, SA-CTS, recency, RL success/decay,
  discard, generated tsvector, and `downgrade -1` + re-upgrade.
- Data reality check: all 813 local `data/vectors/*.db` files contain zero rows
  (the extractor historically never fired), so the live copy moved nothing.
  Backup taken first: `/tmp/opencode/phase4-backup/vectors-20261116T000024.tgz`.
- Known limit: Postgres FTS uses `simple` (no stemming), while SQLite FTS5
  tokenizes differently; retrieval parity is behavioural, not byte-identical.
- Keep `data/vectors/` for one week after switching production to Postgres.
- Production `alembic upgrade head` done 2026-11-16T22:20Z (Coolify deploy): head
  `c2d3e4f5a6b7` verified live, `memory_vectors` table verified, `migrate_vectors_to_pg.py`
  executed (0 memories pending, dry_run=False).

### Phase 5 — artifacts + metrics  [x] done 2026-11-15

- `aios/core/tracing.py`: metrics snapshots go to logger `aios.metrics` as one
  JSON object per snapshot instead of appending `data/metrics/<day>.jsonl`.
  Payload keys unchanged (`llm_calls`, `llm_tokens`, `tool_calls`, `errors`,
  `_ts`). Any consumer of the old JSONL path must switch to that logger.
- `aios/core/storage.py`: one WARNING on startup when the backend is `local`
  and the role is not `all` — local artifacts need a shared volume across
  replicas, S3 required otherwise. No raise, no new config.
- `aios/core/telemetry.py` unchanged (memory -> DB, no local files).
- `tests/test_metrics_logging.py`: log record emitted, no metrics dir created.
- Gate: artifact written by replica A readable by replica B — still requires
  S3 or a shared volume in a real multi-node deployment; not yet exercised.

### Phase 6 — channel ingress  [x] done 2026-11-16

Telegram webhook mode when public base URL configured; IMAP only in gateway
role. Gate: webhook message received and deduped; lease loss stops the loop.

- `aios/config.py`: `public_base_url` (empty → polling unchanged) and
  `telegram_webhook_secret`. Webhook mode needs both; missing either keeps the
  existing poll loop, so a half-configured deploy cannot go silent.
- `aios/channels/telegram.py`: `start()` calls `setWebhook` when configured and
  skips polling; otherwise polls. Both inbound paths now pass a stable
  `msg_id` (`telegram:{chat}:{message}`) so `process_inbound` dedups by
  `channel_message_id` — the in-memory `_seen` set was lost on restart.
- Fixed the poll lease: it was taken `NX` and **deleted at the end of every
  cycle**, so two replicas raced each cycle. It is now renewed with `SET XX EX
  60` each cycle; if renewal fails the loop stops. Compare-and-delete on exit.
- `aios/api/telegram_webhook.py`: `POST /api/telegram/webhook/{connection_id}`
  verifies `X-Telegram-Bot-Api-Secret-Token` (per-connection `webhook_secret`
  else the global setting) with `hmac.compare_digest`, fails closed with 503
  when unconfigured and 401 on mismatch.
- `aios/channels/email_.py`: `start()` refuses to open the IMAP poller outside
  the gateway/all role, even if called directly.
- Gate: 4 passed (`tests/test_telegram_webhook.py`) covering fail-closed auth,
  wrong secret, dispatch with stable `msg_id`, and lease-loss loop stop.
  77 passed in channel/delivery/runtime-role subset. Full suite: 1436 passed,
  11 skipped in 13:31 (`pytest -n 4 --dist loadfile`, EXIT=0) — Phase 7's 1432
  plus the 4 new tests, no regressions.
- Known limit: webhook registration is best-effort at `start()`; a failed
  `setWebhook` falls back to polling rather than retrying, so a transient
  Telegram error at boot means polling until the next restart.

### Phase 7 — REST turns become events  [x] done 2026-11-16

- `POST /api/conversations/{id}/messages` no longer runs the agent. It writes
  the user row, keeps the limit check and the human-handover short circuit,
  then enqueues `aios.tasks.jobs.conversation_turn_job` and returns
  `reply=null`. The response model already allowed null (handover path), so
  this is contract-compatible; clients must read the reply from
  `GET /messages` or the agent websocket.
- `aios/tasks/jobs.py`: `conversation_turn_job` does the agent/team routing
  that used to live in the endpoint, and is idempotent on the user message id
  (`extra_data.turn_done`), so an ARQ retry cannot answer twice.
- Fixed a duplicate-reply bug found while moving it: `AgentRuntime.run_stream`
  already persists the assistant row when given a session, and every caller
  wrote a second one. `_ensure_reply_row` now inserts only when the runtime did
  not. Applied to `process_inbound` as well — the same root cause affected every
  answered channel turn, not just REST.
- `aios/tasks/queue.py`: a failed Redis pool creation now sets a 5s cooldown.
  Before, every webhook/turn paid arq's full retry delay (~5s) whenever Redis
  was down.
- Gate: 55 passed in the REST/conversation/turn subset; 45 in
  delivery/channels/worker-registry/dead-letter/runtime-role. Full suite below.
- Deliberately not changed: `POST /messages/stream`, dashboard test/chat, and
  promptlab/eval still run inline. A human is watching those; they are bounded
  and their output is streamed, so queueing them needs a token channel first.
- Known limit: if Redis is down, the turn is written to the outbound DLQ and the
  user row exists with no reply. Same failure mode channel inbound already has.

Deferred / rejected: removing Redis (separate project); serverless/edge targets
(`sandbox.py` + cron subprocesses need a real OS process).

### Phase 8 — shared agent state  [x] done 2026-11-16

Original gap list: health tracker, telemetry reads, context cache, scheduler
bookkeeping, tool cache. Doing the correctness half first.

- `aios/core/agent_health.py`: status is now mirrored to Redis
  (`aios:health:{agent_id}`, 7d TTL) on every failure/success/reset, and
  `refresh()` merges the shared status into the local counters. `main.py` runs
  a 5s sync task. Before this, a worker that marked an agent `stopped` did not
  stop it on any other worker, and the API replica always reported `healthy`
  because it never ran the agent. Counters stay local by design.
- `aios/api/analytics.py` `/telemetry/summary`: reads `agent_metrics` from the
  DB (sample-weighted average) instead of the calling process's unflushed dict,
  which on the API role was usually empty. `/telemetry/agents` was already
  DB-backed.
- `aios/core/agent.py` / `aios/core/context_manager.py`: the in-process context
  cache could shadow newer turns. The old guard compared `cached.message_count`
  (includes tool rows) with `len(recent)` (DB replay, tool rows filtered and
  capped at 20), so once the cache held ~20 entries it always won — a replica
  that had answered an older turn kept serving that block while another replica
  advanced the conversation. `SavedContext.saved_at` plus
  `_cached_context_is_fresh()` now allows at most one DB row newer than the save
  (the current user message) before the cache is discarded.
- `tests/test_router.py`: clearing the process-global response/context caches
  between tests. The new freshness rule made the context identical across
  tests, which exposed a latent leak: the response cache served the previous
  test's answer and the provider was never called (`calls == []`). Production
  behaviour is unchanged; tests were passing by accident.
- Remaining Phase 8: tool_cache is a 5-minute per-process cache (miss
  re-executes; sharing it would make staleness global, not smaller). Scheduler
  `_processes` bookkeeping is per-process; the dashboard only sees the local
  worker's queue, and actual concurrency is bounded by ARQ `max_jobs`. Neither
  is a correctness bug.
- Gate: 6 passed in `tests/test_shared_state.py` (adds the cache-freshness
  watermark), 37 passed in `tests/test_router.py` with per-test cache clearing.
  Full suite: 1442 passed, 11 skipped in 13:38 (`pytest -n 4 --dist loadfile`,
  EXIT=0) — the P1/P2 gate's 1441 plus the watermark test, no regressions.

### P1/P2 statelessness fixes  [x] 2026-11-16

- IMAP lease was never exclusive: the key embedded a fresh uuid each cycle and
  was written with `SET NX`, so `NX` always found an unused key. Now the key is
  stable and the owner is the value; `SET NX` to take, owner-checked Lua to
  renew/release. Same bug existed in the Phase 6 Telegram lease and is fixed
  with the same helpers (`acquire_lease` / `renew_lease` / `release_lease` in
  `aios/tasks/queue.py`).
- `aios/core/storage.py`: split roles (`api`/`worker`/`gateway`) with
  `storage_backend=local` **and no explicit setting** now refuse to boot.
  S3, or an explicit `AIOS_STORAGE_BACKEND=local` for a shared volume, is
  required. `all` (single process) keeps the old warning.
- `aios/tasks/worker.py`: WhatsApp opt-out/cooldown state is rehydrated every
  5 minutes, closing the window where a runtime opt-out recorded by another
  replica was not seen by the delivering worker. DB was already the truth.
- Still documented, not changed: per-process circuit breakers, ARQ nonce dedup,
  in-memory rate-limit fallback (all deliberate); `evolution` outbound batching
  splits across gateway replicas if more than one is running; scheduler and
  cache bookkeeping above.
- Gate: 5 new tests in `tests/test_shared_state.py` (lease exclusivity, IMAP
  lease wait/lost, health publish, health refresh, DB-backed telemetry), plus
  the 4 Telegram webhook tests updated for the owner-scoped lease.
  Full suite: 1441 passed, 11 skipped in 13:25 (`pytest -n 4 --dist
  loadfile`, EXIT=0) — Phase 6's 1436 plus the 5 new tests, no regressions.

## Done

- Tier 2 + Tier 3 of the differentiation plan (2026-11-17, uncommitted):
  - `GET /dashboard/approvals` (+ `POST /{id}/approve|reject`): the HITL queue the
    API exposed but the dashboard never showed. Decisions are written through
    `approval_manager` with `decided_by`/`decided_at`, org-scoped.
  - `GET /dashboard/contracts`: read-only viewer of `WORKFLOW_CONTRACTS` plus the
    agents that declare `workflow_class` and their ICM binding state.
  - `GET /api/analytics/unit-cost`: `usage_records` → BRL cost per conversation
    and per qualified lead. Reports `has_cost_data: false` when the meter never
    wrote a row — absent, not zero. Analytics page has the matching card.
  - `GET /api/analytics/outcomes?days=&baseline_days=`: two-window comparison
    with `previous`, `delta`, `comparable`; `days=0` keeps the legacy shape.
  - Gate: `tests/test_paid_workflow_e2e.py` (11 passed) walks contract →
    runtime → approval → outcome, plus the three read-only surfaces.
    Full suite: 1464 passed, 11 skipped; `ruff check .` clean.

- Internal tool first + strategy items 2-5 (2026-11-17, from the startup/roadmap
  PDF assessment; item 1 — `aios/verticals/` as a *product layer* — was
  explicitly excluded by the operator, the package exists only to own paid
  workflow contracts):
  - Model registry: names, role floors and prices moved to `aios/config.py`
    (`MODEL_TIERS`, `MODEL_ROLE_MIN_TIER`, `MODEL_COST_IN_OUT`,
    `MODEL_COST_UNKNOWN_PER_1K`). `aios/core/router.py` and
    `aios/core/tracing.py` import them; unknown models are priced at the
    frontier fallback, never at zero. Gate:
    `tests/test_router.py::test_ladder_and_prices_come_from_the_registry`.
  - ICM-X contractual for paid workflows: `aios/icm/agent_binding.py` adds
    `assert_paid_workflow_contract()`, called from `AgentRuntime.__init__`.
    An agent declaring `extra_data["workflow_class"]` must have a contract
    owned by a vertical and an `extra_data["icm"]` binding, or it refuses to
    run. Opt-in ICM-X remains for internal utilities. Gate:
    `tests/test_icm_paid_contract.py`.
  - Business outcome analytics: `GET /api/analytics/outcomes` reports enquiries,
    answered/unanswered, first-response seconds, qualified leads, follow-ups,
    human approvals, attributed deals and value — with
    `attribution_source` / `attribution_confidence` always present. Window is
    the 500 most recent conversations and says so. Gate:
    `tests/test_outcome_analytics.py`.
  - Lint baseline cleared: `ruff check .` → `All checks passed!` (was 97
    findings under the project's own E4/E7/E9/F selection).
  - Billing disabled (commented): `aios/api/router.py` no longer mounts
    `billing_router`; `/dashboard/billing` page commented out; billing nav/link
    in `base.html`, `dashboard.html`, `proposal.html` commented; `billing.py`
    header states it is not mounted.
  - Multi-tenant signup disabled (commented): `/api/auth/register` and both
    `/dashboard/register` handlers commented out; accounts are provisioned by
    the operator. `tests/test_auth.py` provisions users directly,
    `tests/test_billing.py` / `tests/test_registration_closed.py` assert the
    surfaces are absent (404).
  - Kept on purpose: `org_id` scoping and approval/tenant-safety checks are data
    isolation, not a commercial surface. `PLANS` and `core/limits.py` remain
    because the fleet uses them for SLA/cost guardrails; `AIOS_INTERNAL_MODE`
    already bypasses quota gates.
  - Gate: `1453 passed, 11 skipped in 13:54` (`pytest -n 4 --dist loadfile`,
    `EXIT=0`); `ruff check .` → `All checks passed!`.

- Fleet agent tools & capabilities remediated (2026-11-17):
  - Audited all 12 operational agents against prompts, tool registry, and ICM manifests.
  - Resolved fleet-wide escalation gap: added `ask_team_manager` and `notify_human` across worker agents (`sales-sdr`, `sales-closer`, `dev-frontend`, `dev-backend`, `red-agent`, `blue-agent`, `Data Analyst`, `Data Scientist`).
  - Added `cal_booking`, `calculator`, `whatsapp_template` to `sales-sdr`; added `lead_score`, `cal_booking`, `web_search` to `sales-closer`; added `crm_pipeline_stats`, `cal_booking` to `sales-manager`.
  - Added `request_build` to `dev-backend` and `dev-manager`; added `proactive_alerts` to `security-manager` and `data-manager`.
  - Cleaned obsolete prompt references (`knowledge` -> `rag_search` in `sales-sdr`, removed `storage_save` reference in `Data Analyst`).
  - Updated stage manifests in `aios/icm/team_workspaces.py` to allow the new tools under ICM governance.
  - Created and executed `scripts/remediate_agent_tools.py` in production; re-seeded all 6 ICM workspaces under `/data` with `scripts/provision_icm_fleet.py`. All 12 operational agents verified loading 100% of their tools with `missing=[]`.
  - Tests green: `pytest tests/test_icm_x.py` (15 passed), `pytest tests/test_fleet_verify.py` (7 passed).

- Stateless migration deployment (Phases 0-8) verified in production (2026-11-17):
  - Coolify deployed commit `a2ee3de` (~2026-11-16T22:20:37Z).
  - App and worker containers running `38908ddf-a875-4105-a93f-a4570513911f_app:a2ee3dee9db3d9317a8c7efb72668b0442c956fe`.
  - Alembic migrations ran successfully up to `c2d3e4f5a6b7` (head).
  - `memory_vectors` table verified in Postgres; `scripts/migrate_vectors_to_pg.py` executed cleanly.
  - `/health/ready` reports HTTP 200 with role=`all`, db=`ok`, migrations=`ok`, redis=`ok`, rag=`ok`.
  - `/health` reports `hnsw: true`. Worker running cleanly with `j_failed=0`.

- Right-sized for the 4 vCPU / 8 GB host (commit `dde0d83`, deployed
  2026-11-13T10:34:08Z):
  - gunicorn `--workers 1` (was 2): one scheduler, one DB pool, one telemetry
    flush per release instead of two.
  - DB pool `5 + 5 overflow` per process (was `10 + 20`); ARQ `max_jobs` is now
    `AIOS_WORKER_MAX_JOBS`, default 5 (was hardcoded 20).
  - Cron advisory-lock holder now `COMMIT`s right after acquiring the session
    lock, and the loser closes its session. The two long-lived
    `idle in transaction` backends are gone; one advisory lock remains.
  - Daily backup runs once (ARQ `backup_job` removed; `deploy/backup.sh` via
    the cron scheduler is the single path), strips `+asyncpg` from the URL,
    rejects empty archives, keeps 7 days. Verified in the container: a real
    dump is 31 KB and `gzip -t` passes.
  - Compose: postgres 512M with `shared_buffers=256MB`,
    `effective_cache_size=1GB`, `max_connections=60`; app 1G; worker 512M;
    otel 128M; json-file logs capped at 10m x 3. Kokoro untouched (2G cap).
  - Tests: `tests/test_backup_script.py` added; catalog + config suites pass.
    `tests/test_config.py::test_health_endpoints` still 503 locally because the
    local sqlite DB is unversioned (`alembic_version` missing) — pre-existing,
    unrelated to this change; production `/health/ready` returns 200.
  - Host cleanup: unused Docker images and build cache pruned. Disk
    91% -> 87% (9.7 GB free, was 6.6 GB). The earlier "26 GB reclaimable"
    figure from `docker system df` was shared-layer accounting and did not
    materialise; used memory fell 6.2 GB -> 4.7 GB and available memory
    1.5 GB -> 3.0 GB after the container restarts.
  - Note: pruning removed older app/worker image tags, so Coolify's
    image-level rollback for previous releases is gone; redeploy the git commit
    instead.
- Model picker now uses the live OpenRouter catalog instead of a hardcoded
  list (`aios/dashboard/templates/_model_picker.html`,
  `aios/dashboard/app.py:_catalog_models`). Agent form and wizard fetch
  `/dashboard/api/models` on load, group by provider with a "Recém-lançados"
  section (newest by `created`), and keep direct/local extras. Only `:batch`
  is excluded; `:free` variants stay selectable for testing (rate-limited, cost
  0, id suffix makes them obvious), as do non-text/unpriced exclusions.
  Catalog cached 6h, `?refresh=1` bypasses. Production catalog has 388 chat
  models including 15 `:free`; newest includes `google/gemini-4-hydrogen`,
  `google/gemini-4-carbon`, `anthropic/claude-fable-5.2`. Tests:
  `tests/test_model_catalog.py` (4 passed). Commits `7e73174` + `d2deeee`,
  deployed 2026-11-13T08:37:16Z.
- Manager consolidation: red-manager + blue-manager merged into one
  `security-manager` (`scripts/merge_security_managers.py`). Both `red` and
  `blue` teams point at it; red-manager is archived (row kept for conversation
  FKs), so the fleet is 12 operational agents. `security_ops/security_review`
  stage bound (timeout 240s, 10 allowed tools, denied CRM/email side effects).
- Team workspaces and stage manifests (task 5): `aios/icm/team_workspaces.py`
  defines `sales_ops`, `dev_ops`, `red_ops`, `blue_ops`, `security_ops`,
  `data_ops` (12 stages). `scripts/provision_icm_fleet.py` seeds under `/data`
  and binds agents. Production provisioned for Pixor org.
- Event subscriptions (task 3): applied to sales-sdr, sales-closer,
  sales-manager, dev-manager, red-agent, blue-agent, security-manager.
  Data agents remain request-driven on purpose (no matching producer).
- Autonomy policy (task 2): explicit `autonomy=autonomous`, `autonomous=true`,
  `hitl_enabled=true`, `max_trials=3` on all operational agents.
- ICM-X applied to standalone/proactive agent runs (task 4):
  - `aios/icm/agent_binding.py` binds `AgentRuntime` to a stage manifest from
    `extra_data.icm` (`workspace_id`, `stage_id`).
  - Stage allowlist is intersected with the agent's own `allowed_tools`;
    `denied_tools` are added; `timeout_seconds` caps each run and emits a
    `STREAM_ERROR` on timeout.
  - Layered context (L0-L3) is injected once per autonomous run.
  - Provenance + artifact written per run; `proactive_event_job` now includes
    `icm_provenance` in `agent.proactive_completed`.
- Verified in the live container: `security-manager` binds `security_review`
  240s, 10 allowed tools, `security_ops` context 1267 chars; `sales-sdr` binds
  `sdr_prospecting` v1.0.0, timeout 180s, allowlist 10 tools, denied
  `crm_merge_deals`/`crm_stale_deals`.
- Commit `d76cbc1` deployed; deployment finished 2026-11-12T22:04:03Z.

- Verified Telegram test channel script runs: `scripts/create_agents_test_telegram_channel.py` upserts `agents-test-telegram-s9` row for org `test-org` successfully.
- Implemented ICM-X Stage Adapter & Workflow Integration (`feat(icm): connect workflow engine to stage adapter and governance`):
  - Created `aios/icm/adapter.py` (`ICMStageAdapter`): resolves stage contracts, enforces allowed/denied tool governance, loads bounded layered context (`L0` identity, `L1` routes, `L2` stage context, `L3` static guidelines), sets execution timeout limits, records execution provenance, and saves output artifacts.
  - Extended `WorkflowNode` and `WorkflowEngine` in `aios/core/workflow.py` to optionally bind `stage_id`, `workspace_id`, and `stage_manifest`, triggering pre/post execution hooks and provenance recording.
  - Added `seed_b2b_lead_research_workspace` scaffolding helper in `aios/icm/workspace.py`.
  - Added unit tests in `tests/test_icm_x.py` for workspace seeding, allowed tool execution, provenance emission, and tool governance denial.
  - Verified tests pass (`15 passed` in `tests/test_icm_x.py`, `3 passed` in `tests/test_workflows_async.py`).
  - Verified `ruff check aios/` passes cleanly.
  - Updated knowledge graph with `graphify update .`.

- PR #1 (`feat/icm-x-foundation`): Verified CI completed green (lint, typecheck, gitleaks, test (3.14), build, docker-compose) and merged into `main` (commit `d3cc299`).
- Diagnosed remote GitHub branch `origin/feat/icm-x-foundation` and associated PR #1 (`feat(icm): add opt-in ICM-X workspace and stage contract foundation`).
- Located failing CI job `test (3.14)` on GitHub Actions caused by `test_yaml_manifest_loads` in `tests/test_icm_x.py` omitting `max_cost_usd: 0.05` for `mode: llm`.
- Fixed `tests/test_icm_x.py` to supply `max_cost_usd: 0.05`.
- Verified all 14 tests in `tests/test_icm_x.py` pass cleanly locally.
- Verified `ruff check` passes cleanly.
- Updated knowledge graph with `graphify update .`.
- Pushed commit `7b29521` to `origin/feat/icm-x-foundation`. CI is triggered.

- Model selector (`aios/core/model_select.py`): scores are now absolute anchors
  (frontier index scale, $1/1M blended = 0.5 cost score, 1M ctx = 1.0) instead
  of cohort-relative normalisation. Ranks no longer flip when an unrelated model
  enters the catalog; a live refresh moved `glm-5.3-flash` to $0.016/$0.148 and
  the picks were recomputed from that. `tests/test_model_select.py` still green.
- Full suite confirmed green: `1361 passed, 19 skipped` in 43:16, exit 0
  (`/tmp/opencode/full_pytest4.log`). `_fresh_db` hardening verified.
- `graphify update .` run after the fix (no topology changes).

Full-suite runs `full_pytest2.log` (4 failed, all fixed) and `full_pytest3.log`
(3 failures, one module). Root cause of the `full_pytest3` cluster is test-DB
state, not product code: the first 23 test files (through
`tests/test_curated_memory.py`) pass in isolation and as a prefix run
(`/tmp/opencode/prefix_curated.log`, 374 passed). `_fresh_db` used to
`drop_all` inside `try/except: pass`; a stale journal/leaked connection made
that fail silently, so `create_all` hit "already exists" and later tests saw
"no such table".

Fix: `tests/conftest.py::_fresh_db` now disposes the engine and deletes
`tests/test.db*` before each test, then `create_all`. Verified:
`test_crm_tools + test_curated_memory + test_deployment + test_fleet_verify`
→ 66 passed. `.gitignore` widened to `tests/test.db*`.

Earlier in the session (all verified):

- `tests/test_whatsapp_webhook.py` — bytes, not dict, to `_verify_evolution_sig`.
- `tests/test_webhook_signatures.py` — Mailgun timestamp must be current (300s window).
- `tests/test_team_managers.py` (×2) — `cal_booking` added to manager template.
- evolution channel/e2e tests pass raw bytes + set `state.aios_raw`.
- `tests/test_login_allowlist.py::test_refresh_allowed_for_listed` uses `_issue_refresh`.
- Deployment/fleet verification: `aios/core/deployment.py`, `aios/core/fleet_verify.py`,
  API routes, dashboard routes/cards, `/health/ready`, `verify_fleet_job`,
  `tests/test_deployment.py`, `tests/test_fleet_verify.py`.

## Notes for next session

- Tests need pytest in the venv: `.venv/bin/python -m pip install pytest pytest-asyncio`.
- Deploy is disk-bound: the VPS root is 75GB and Docker images alone are ~30GB.
  Coolify **pulls every service** in `docker-compose.coolify.yml` on each deploy,
  profiles ignored. That is why Cal.com moved to `docker-compose.calcom.yml`
  (~4.5GB image) and Kokoro TTS is pinned by digest instead of `latest`
  (it re-downloaded ~5GB per deploy). Keep both rules: no heavy services in the
  Coolify file, no floating tags.
- If a deploy fails on "no space", free space before retrying: remove old
  `<app>_app:<sha>` / `_worker:<sha>` images, `docker builder prune -af`, then
  check `df -h /`. Do not retry at <3GB free.
- Disk-full also corrupted the Redis AOF (`Bad file format reading the append
  only file`). Fix used: `docker run --rm -v <app>_redis-data:/data redis:7-alpine
  sh -c 'printf "y\n" | redis-check-aof --fix /data/appendonlydir/appendonly.aof.manifest'`.
  A backup was kept at `/data/appendonlydir.bak` inside the volume.
- Do not remove the `_stub_deploy_probe` autouse fixture; it keeps tests off paid
  provider APIs.
- Always start a full run from a clean DB (`rm -f tests/test.db*`); the fixture now
  does this per test, but a leftover file still masks nothing anymore.
