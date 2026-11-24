# Production configuration (Supabase main DB)

AIOS app + worker use Supabase as the main database. The standalone `postgres`
container in `docker-compose.coolify.yml` remains only for Evolution's own
schema; it is not the AIOS DB.

## DSN

Set `AIOS_SUPABASE_DATABASE_URL` in Coolify as a secret. Shape:

```bash
AIOS_SUPABASE_DATABASE_URL=postgresql+asyncpg://postgres:<secret>@aios-supabase-db-8778:5432/aios
```

- Host `aios-supabase-db-8778` is the existing socat bridge on the Coolify
  network. If recreated, reattach it with
  `sudo -n docker network connect coolify aios-supabase-db-8778`.
- DB is `aios`; AIOS tables live in schema `aios`.
- Do **not** append `?schema=` or a `search_path` query param. `aios/db/engine.py`
  sets `search_path = aios, public, extensions` on every connection; Alembic
  writes `aios.alembic_version_aios`.
- `postgres` is the bridge DB user already in use. Keep the password in the
  secret manager only. Do not print it, paste it in chat, or commit it.

`docker-compose.coolify.yml` maps that secret into app/worker as
`AIOS_DATABASE_URL`. Both processes must resolve to the same DSN.

## Required environment

| Variable | Notes |
|----------|-------|
| `AIOS_SUPABASE_DATABASE_URL` | Supabase DSN above; secret |
| `AIOS_JWT_SECRET` | `openssl rand -hex 32`; stable across deploys |
| `AIOS_REDIS_URL` | Compose builds from `REDIS_PASSWORD` |
| `AIOS_APP_URL` | Canonical public origin |
| `POSTGRES_PASSWORD` | Standalone DB for Evolution only |
| `REDIS_PASSWORD`, `EVOLUTION_API_KEY` | Compose-required secrets |

LLM keys are intentionally empty in `.env.coolify.example`; set the chosen
provider key in Coolify only. No live model calls are needed for DB cutover.

## Connection budget

Each process opens up to `AIOS_DB_POOL_SIZE + AIOS_DB_MAX_OVERFLOW` connections
(default 5 + 5 = 10). Count app replicas + worker replicas + any gateway before
raising pools. Supabase connection limits apply, not the old compose
`max_connections=60`.

## Version truth

Expected single code Alembic head: `e1f2a3b4c5d6`. Supabase `aios` schema
pre-cutover revision: `e7f8a9b0c1d2`. Verify with
`scripts/cutover_supabase_main_db.py`; the guard refuses multiple heads,
`alembic stamp head` on a failed migration, and any revision not actually
present in the database.

Cutover steps: `docs/DEPLOY.md`.
