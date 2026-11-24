# Deploy: Supabase as AIOS main DB (cutover runbook)

Scope: historical runbook to repoint AIOS **app + worker** from standalone
`postgres:5432/aios` to Supabase DB `aios`, schema `aios`, through bridge
`aios-supabase-db-8778:5432`. Cutover already applied for current app; steps
below are reference/recovery unless a future wave needs them. ARVO keeps its
own DSN/schema (`arvo`) and SSO ticket bridge. Standalone Postgres stays alive
for Evolution only.

This runbook writes to prod when a human executes it. The repo change itself
does not touch prod. No LLM/model call is needed.

## Known facts / targets

- Current live AIOS DSN host (verified): `aios-supabase-db-8778:5432/aios`,
  the Supabase bridge; below called "the DB the app points to". Step 0 still
  records it before any change; never print credentials.
- Supabase service: `x7cec17of43bremk02s521wj`, DB `aios`, schema `aios`.
- Supabase `aios` pre-cutover revision: `e7f8a9b0c1d2`.
- Repository migration head: `e1f2a3b4c5d6`, via
  `alembic/versions/icm_side_effect_dedupe.py` (`f0e1d2c3b4a5`) and
  `alembic/versions/schema_gaps_creds_crm_kpi.py` (`e1f2a3b4c5d6`); committed
  in `e46771e`. Commit/push any pending integration-wave code before building a
  future image.
- Committed AIOS HEAD / current deployed image: `3aa2db5` (Coolify `#805`,
  routing fix only). Integration-wave code remains uncommitted locally: not
  deployed, signed delivery unverified. Migrations committed in `e46771e`
  must still be included in any future image.
- Current app DB is the Supabase bridge `aios-supabase-db-8778:5432/aios`.
  Alembic head `e1f2a3b4c5d6` reached in app; `/health/ready` `200 migrations:ok`.
  Supabase cutover already applied for this app — no longer a future gate here.
  Section 0a is conditional/historical: use only if readiness regresses.
  Remaining human gate: integration-wave code if still uncommitted. Migrations
  committed in `e46771e` must still be included in any future image.
- AIOS engine sets `search_path = aios, public, extensions`; Alembic version
  table is `aios.alembic_version_aios`.

## 0. Prepare (human gate)

1. Freeze deploys and writes to AIOS during the window.
2. Resolve container names:

   ```bash
   docker ps --format '{{.Names}}\t{{.Image}}' | grep -E 'aios|evolution|postgres'
   ```

   Set placeholders below: `<app_container>`, `<worker_container>`,
   `<postgres_container>`.
3. Read the DSN from the secret manager into a shell variable. Never paste it
   in chat or a command line:

   ```bash
   read -rs -p 'Supabase DSN from secret manager: ' AIOS_SUPABASE_DATABASE_URL
   echo   # newline only, do not echo the DSN
   ```

4. Confirm bridge on the Coolify network. If lookup fails, stop and reattach:

   ```bash
   docker exec <app_container> getent hosts aios-supabase-db-8778
   # if missing, human gate:
   sudo -n docker network connect coolify aios-supabase-db-8778
   ```

5. Record the old DSN **host only**, never the password:

   ```bash
   docker exec <app_container> python -c 'import os;from urllib.parse import urlsplit;u=urlsplit(os.environ["AIOS_DATABASE_URL"]);print(u.scheme,u.hostname,u.port,u.path)'
   ```

   Record the actual value; do not assume a host.

6. If integration-wave code/migrations are still uncommitted, commit/push them
   first (human gate). Build an image from that commit and note its tag as
   `<migration_image>`. It must contain
   `alembic/versions/icm_side_effect_dedupe.py` and
   `alembic/versions/schema_gaps_creds_crm_kpi.py`. Do not restart app/worker
   on it until step 4 finishes.

## 0a. Immediate readiness repair on current deployed image (human gate)

Only if readiness regresses: separate from the Supabase cutover. Previously
observed `/health/ready` `503 behind:b8c9d0e1f2a3->d0e1f2a3b4c5`; apply
committed head `d0e1f2a3b4c5` to the DB the app actually uses. Do not change
DSNs here.

Human gate: confirm a dump of the DB the app points to exists. Then use the
currently deployed image and the app container's existing `AIOS_DATABASE_URL`
(no secret in argv):

```bash
docker exec <app_container> sh -c 'cd /app && alembic upgrade head && alembic current'
```

Stop on any failure. Do **not** `alembic stamp head`; `deploy/entrypoint.sh`
only stamps a genuinely unversioned DB (no version row) and fails closed
otherwise (`deploy/entrypoint.sh:91-113`). Re-check `/health/ready`. This repair
does not make worktree head `e1f2a3b4c5d6` reachable; the cutover below still
needs the new image.

## 1. Dry-run preflight (read-only)

Run the guard from `<migration_image>` (step 0, item 6), not the current
deployed image. Mount the guard read-only and pass the DSN on stdin so it never
appears in `ps` or logs. `--entrypoint bash` bypasses the image's default
`deploy/entrypoint.sh` auto-migration:

```bash
docker run --rm -i --network coolify --entrypoint bash \
  -v "$PWD/scripts/cutover_supabase_main_db.py:/app/scripts/cutover_supabase_main_db.py:ro" \
  <migration_image> -c '
  read -rs AIOS_SUPABASE_DATABASE_URL
  export AIOS_SUPABASE_DATABASE_URL
  python /app/scripts/cutover_supabase_main_db.py
' <<< "$AIOS_SUPABASE_DATABASE_URL"
```

Exit code must be `0`. This guard is for the Supabase cutover target, not the
readiness repair in section 0a. The script checks DSN shape/host/user/db, TCP to the
bridge, schema `aios`, `pgvector` extension, code head, version row, and that
the DB revision is either `e7f8a9b0c1d2` (upgrade needed) or already
`e1f2a3b4c5d6`. Any mismatch exits `1`; do not continue. Multiple Alembic heads
also exit `1` — resolve/merge them before any cutover; `alembic upgrade head`
is not safe with a fork.

## 2. Backups (human gate)

Dump the DB the app points to (host recorded in step 0):

```bash
docker exec <postgres_container> sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > aios_standalone_pre_supabase_cutover.dump
```

Dump Supabase `aios` schema before migration. Password goes via stdin, not
argv. Bridge must resolve on `coolify`:

```bash
read -rs -p 'Supabase DB password: ' SUPABASE_DB_PASSWORD
docker run --rm -i --network coolify postgres:15 bash -c '
  read -rs PGPASSWORD; export PGPASSWORD
  pg_dump -h aios-supabase-db-8778 -p 5432 -U postgres -d aios -n aios -Fc
' <<< "$SUPABASE_DB_PASSWORD" > aios_supabase_schema_pre_upgrade.dump
unset SUPABASE_DB_PASSWORD
```

Require non-empty dumps and record hashes:

```bash
test -s aios_standalone_pre_supabase_cutover.dump
test -s aios_supabase_schema_pre_upgrade.dump
sha256sum aios_standalone_pre_supabase_cutover.dump aios_supabase_schema_pre_upgrade.dump
```

Store both outside the prod container. No cutover without these two files.

## 3. Capture RLS/policy baseline (read-only)

Run before migration, save output; repeat after DSN switch and diff:

```bash
read -rs -p 'Supabase DB password: ' SUPABASE_DB_PASSWORD
docker run --rm -i --network coolify postgres:15 bash -c '
  read -rs PGPASSWORD; export PGPASSWORD
  psql -h aios-supabase-db-8778 -p 5432 -U postgres -d aios -X -v ON_ERROR_STOP=1 -At <<SQL
SELECT count(*) FROM pg_policies WHERE schemaname = \$\$aios\$\$;
SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = \$\$aios\$\$ AND c.relrowsecurity;
SQL
' <<< "$SUPABASE_DB_PASSWORD" | tee aios_rls_before.txt
```

Same command after cutover → `aios_rls_after.txt`; `diff` must be empty.

## 4. Upgrade Supabase `aios` schema BEFORE switching DSN (historical for current app)

Already applied for current app; use only for a future target. In that case app
still points at the DB recorded in step 0. Run migration from a shell in
`<migration_image>` (step 0, item 6) against the Supabase DSN only.
`--entrypoint bash` avoids the image's default `deploy/entrypoint.sh`, which
would auto-run `alembic upgrade head` against the container's own
`AIOS_DATABASE_URL`:

```bash
docker run --rm -i --network coolify --entrypoint bash <migration_image> -c '
  read -rs AIOS_DATABASE_URL
  export AIOS_DATABASE_URL
  cd /app && alembic upgrade head && alembic current
' <<< "$AIOS_SUPABASE_DATABASE_URL"
```

Expected final revision: `e1f2a3b4c5d6` (chain `d0e1f2a3b4c5` →
`f0e1d2c3b4a5` → `e1f2a3b4c5d6`). If the image reports a different head or
migration fails, stop. Do **not** `alembic stamp head`; restore
`aios_supabase_schema_pre_upgrade.dump` only with explicit human approval.

Re-run step 1. It must pass with DB revision already at head.

## 5. DSN switch

1. In Coolify, set secret `AIOS_SUPABASE_DATABASE_URL` to the DSN from step 0.
2. `docker-compose.coolify.yml` maps it into app and worker as
   `AIOS_DATABASE_URL`; deploy app + worker from the updated compose using
   `<migration_image>`. Do not deploy/restart app + worker before step 4
   finishes: the new image's entrypoint auto-runs `alembic upgrade head`
   against `AIOS_DATABASE_URL` (`deploy/entrypoint.sh:60-123`).
3. Confirm both containers resolved to Supabase (host only, no secret printed):

   ```bash
   for c in <app_container> <worker_container>; do
     echo "$c"
     docker exec "$c" python -c 'import os;from urllib.parse import urlsplit;u=urlsplit(os.environ["AIOS_DATABASE_URL"]);print(u.scheme,u.hostname,u.port,u.path)'
   done
   ```

   Expected on both: `postgresql+asyncpg aios-supabase-db-8778 5432 /aios`.

## 6. Verify (all gates required)

### Health

```bash
curl -sS -o /tmp/aios_live.json -w '%{http_code}\n' https://178.105.181.38/health/live
curl -sS -o /tmp/aios_ready.json -w '%{http_code}\n' https://178.105.181.38/health/ready
cat /tmp/aios_live.json /tmp/aios_ready.json
```

Expect `200` for both; ready JSON nests checks under `checks`: need
`checks.db == "ok"` and `checks.migrations == "ok"`. If
`checks.migrations` is `unversioned`, do not call it healthy: re-run step 1 and
check `aios.alembic_version_aios` directly before escalating. `migration_state()`
reads the schema-qualified table on Postgres; the legacy `alembic_version` table
is not authoritative.

### Auth + SSO

Use a real allowlisted account. Password/TOTP come from the human; no token is
printed.

```bash
read -rs -p 'AIOS password: ' AIOS_PW
read -rs -p 'TOTP (empty if disabled): ' AIOS_TOTP
TOKEN=$(curl -sS -H 'Content-Type: application/json' \
  -d "{\"email\":\"<known user>\",\"password\":\"$AIOS_PW\",\"totp_code\":\"$AIOS_TOTP\"}" \
  https://178.105.181.38/api/auth/login \
  | python -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
unset AIOS_PW AIOS_TOTP
curl -sS -o /dev/null -w 'dashboard/channels %{http_code}\n' -b "aios_token=$TOKEN" https://178.105.181.38/dashboard/channels
curl -sS -D /tmp/aios_sso.headers -o /dev/null -w 'sso/arvo %{http_code}\n' -b "aios_token=$TOKEN" https://178.105.181.38/dashboard/sso/arvo
grep -qi '^set-cookie: arvo_token=' /tmp/aios_sso.headers && echo 'arvo_token cookie: set'
unset TOKEN
```

Expect `200` for `/dashboard/channels`, `303` for `/dashboard/sso/arvo`, and
`arvo_token` cookie set. Bad password must still be `401`.

### ARVO untouched

```bash
ARVO_TOKEN=$(awk -F'[=;]' 'tolower($1) ~ /set-cookie: arvo_token/ {print $2}' /tmp/aios_sso.headers | tail -1)
curl -sS -o /dev/null -w 'arvo health %{http_code}\n' https://178.105.181.38/arvo/health/live
curl -sS -o /dev/null -w 'arvo control-center %{http_code}\n' -b "arvo_token=$ARVO_TOKEN" https://178.105.181.38/arvo/control-center
unset ARVO_TOKEN
```

Expect `200` both. ARVO must still use schema `arvo`; do not change its DSN.

### Signed peer probes: in-app path vs public origin

ARVO in-app routes are `/api/v1/integrations/aios/v1/*` (`arvo/app/api/router.py:5,26`);
the public origin mounts ARVO under `/arvo` (`arvo/app/main.py:37`). Use these
exact paths:

- AIOS signed health: `/api/integrations/arvo/v1/health` (GET/POST),
  HMAC-protected on AIOS (`aios/integrations/arvo/routes.py:18,225,230`).
- ARVO signed health: in-app `/api/v1/integrations/aios/v1/health`, public
  `/arvo/api/v1/integrations/aios/v1/health` (GET/POST)
  (`arvo/app/integrations/aios/routes.py:18,264,269`).
- ARVO outbox flush: in-app `POST /api/v1/integrations/aios/v1/outbox/flush`,
  public `POST /arvo/api/v1/integrations/aios/v1/outbox/flush`
  (`arvo/app/integrations/aios/routes.py:751`).

Two contexts — sign the path you send:

- Public-origin probe via `https://178.105.181.38/arvo/api/...` must sign
  `/arvo/api/...`: ARVO verifies `request.url.path`, which includes `root_path`
  (`arvo/app/integrations/aios/routes.py:250`). Signing the prefix-free path
  there fails closed with `401`.
- Internal AIOS client: `AIOS_ARVO_BASE_URL=http://l7p2...sslip.io` is the
  configured target; code signs/sends prefix-free
  `/api/v1/integrations/aios/v1/...` (`aios/integrations/arvo/client.py:16,45-47`)
  and expects forwarding to ARVO `:9777` — code intent, not verified delivery.
  Signed delivery was not verified locally or in prod. Code-level inference:
  `root_path` alone does not inject `/arvo` into that client path.

Secrets stay human-only; print no signature, key or token. Stop on any non-`200`.

Verified deployed topology (read-only, 2026-11-24): public `https://178.105.181.38/api/v1/integrations/aios/v1/health` 404; `/arvo/api/...` and sslip `/api/...` 401 unsigned. Those probes show route presence and the auth gate only — not signed delivery or successful peer delivery. No `arvo-ip-strip` definition found in versioned code (`arvo/app/main.py:50-55` registers only CORS); any strip behavior is external and unverified. Signed live smoke stays human-only.

Browser smoke auth context: `/dashboard/sso/arvo` needs `aios_token`;
`/arvo/control-center` needs `arvo_token` (set by the SSO cookie above).

### RLS / org scoping

1. Repeat step 3 into `aios_rls_after.txt`; `diff aios_rls_before.txt aios_rls_after.txt`
   must be empty.
2. Functional check with two real accounts from different orgs: each account
   must see only its own org rows in `/dashboard/channels` and CRM; a cross-org
   ID must return `404`, not data. This is a human gate with real accounts;
   no synthetic org data is created here.

### Worker

Confirm worker process running and consuming the same DSN (step 5), then check
one known queued job completes. No live LLM credentials are injected by this
runbook.

## 7. Rollback

**Before DSN switch (migration failed):** app still on the DB recorded in step
0. With human approval, restore Supabase `aios` schema only, then stop:

```bash
read -rs -p 'Supabase DB password: ' SUPABASE_DB_PASSWORD
docker run --rm -i --network coolify -v "$PWD:/backup:ro" postgres:15 bash -c '
  read -rs PGPASSWORD; export PGPASSWORD
  pg_restore --clean --if-exists -n aios -d aios /backup/aios_supabase_schema_pre_upgrade.dump
' <<< "$SUPABASE_DB_PASSWORD"
unset SUPABASE_DB_PASSWORD
```

**After DSN switch:** in Coolify set `AIOS_SUPABASE_DATABASE_URL` back to the
pre-cutover DSN recorded in step 0, redeploy app + worker, then repeat step 5
DSN check and health/auth checks. No data is copied back automatically:
that DB holds the pre-cutover state; any writes that happened on Supabase
during the window need explicit human reconciliation before reusing that DSN.

## Human gates summary

- Secret manager supplies Supabase DSN/password; nothing invented or committed.
- Bridge attached to `coolify`; preflight guard exit `0`.
- Both dumps non-empty, hashes recorded.
- Integration-wave code committed/pushed if still pending; `<migration_image>`
  contains head `e1f2a3b4c5d6`.
- Readiness repair historical; Supabase cutover already applied for current
  app; guard re-run passes at head for any future wave.
- Health/ready, auth, SSO cookie, ARVO, RLS baseline diff, worker checked.
- Rollback approved and executed if any gate fails.
