# Pending work

Last updated: 2026-11-13

## Open

- Activate the fleet: `AIOS_OPENROUTER_API_KEY` is still empty in production, so
  all 12 operational agents remain `draft` and no event dispatch reaches them.
  (`red-manager` is archived: 13 rows, 12 operational.) Set the key in Coolify,
  redeploy, then run the deploy/probe for each agent.
- Telegram channel `agents-test-telegram-s9` still has an empty bot token and no
  agent/team assignment.
- Rebuild app container with latest code if changes needed on main branch. (Attempted local rebuild; port 8777 already allocated by Coolify-managed app container; rebuild must run via Coolify deploy or after stopping that container.)


## Done

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
