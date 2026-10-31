# Pending work

Last updated: 2026-10-31

## Open

- None. `main` = `f4cadce` deployed to Coolify (`pixor-aios`), app/worker healthy.

## Done this session

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
