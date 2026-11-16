# AIOS Deployment

## Quick Start (Docker Compose)

```bash
# 1. Clone + configure
cp .env.example .env
# Edit .env: set AIOS_DATABASE_URL, AIOS_JWT_SECRET, AIOS_OPENROUTER_API_KEY, etc.

# 2. Launch
docker compose up -d

# 3. Check health
curl http://localhost:8777/health
curl http://localhost:8777/health/ready

# 4. Open dashboard
open http://localhost:8777/dashboard
```

## Bare metal (systemd)

Docker is only packaging. These units run AIOS directly against Postgres and
Redis. Assumes the repo at `/opt/aios`, a venv at `/opt/aios/.venv`, and env at
`/etc/aios/aios.env` (same variables as `.env.example`).

```bash
# 1. Runtime prerequisites: Python 3.14, PostgreSQL 15+ with pgvector, Redis 7.
sudo apt install postgresql-15 postgresql-15-pgvector redis-server

# 2. User + directories
sudo useradd --system --home /opt/aios --shell /usr/sbin/nologin aios
sudo mkdir -p /etc/aios
sudo chown aios:aios /opt/aios

# 3. Install
cd /opt/aios
sudo -u aios python3.14 -m venv .venv
sudo -u aios .venv/bin/pip install -e .
sudo install -m 600 -o aios -g aios .env.example /etc/aios/aios.env
sudo -u aios editor /etc/aios/aios.env   # set AIOS_DATABASE_URL, AIOS_JWT_SECRET, AIOS_REDIS_URL

# 4. Units
sudo cp deploy/aios-*.service deploy/aios-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aios-migrate.service
sudo systemctl enable --now aios-server.service aios-worker.service aios-gateway.service
sudo systemctl enable --now aios-backup.timer

# 5. Verify
systemctl status aios-server aios-worker aios-gateway
curl -s http://127.0.0.1:8777/health/ready
journalctl -u aios-server -n 50
```

Notes:

- `aios-migrate.service` runs `alembic upgrade head` once per boot; the API and
  worker units `Require=` it, so replicas never race on migrations.
- Bind is `127.0.0.1:8777`; put Caddy/nginx in front for TLS. `deploy/Caddyfile`
  is a starting point.
- Data lives in `/var/lib/aios` (`StateDirectory=aios`). Set
  `AIOS_APP_DATA_DIR=/var/lib/aios` in the env file.
- Backups land in `/var/lib/aios/backups`, retained 7 days.
- Scale API replicas after Phase 3 of the stateless migration; keep the connection
  budget under Postgres `max_connections`.

## Environment Variables

See `.env.example` for all options. Required:

| Variable | Description |
|----------|-------------|
| `AIOS_DATABASE_URL` | PostgreSQL with asyncpg: `postgresql+asyncpg://user:pass@host:5432/db` |
| `AIOS_JWT_SECRET` | 64-char hex: `openssl rand -hex 32` |
| `AIOS_OPENROUTER_API_KEY` | LLM provider key (or OpenAI/Anthropic) |

## Production Checklist

- [ ] `.env` has strong `AIOS_JWT_SECRET` and `AIOS_ADMIN_MASTER_KEY`
- [ ] `AIOS_DEBUG=false`
- [ ] `AIOS_LOG_FORMAT=json` (structured logs for container ingestion)
- [ ] `AIOS_HTTPS_ONLY=true` (requires reverse proxy with SSL)
- [ ] `AIOS_REDIS_URL` set (rate limit persistence + queue)
- [ ] `AIOS_STORAGE_BACKEND=s3` with Supabase/R2/MinIO credentials
- [ ] Alembic migrations run: `alembic upgrade head`
- [ ] Webhook secrets set for WhatsApp/Evolution channels
- [ ] Stripe keys + price IDs set (if billing enabled)
- [ ] SMTP configured (email verification + password reset)
- [ ] OAuth configured (Google/GitHub client IDs + secrets)
- [ ] `AIOS_SENTRY_DSN` set for error tracking

## Database Migrations

```bash
# Auto-generate migration after model changes
alembic revision --autogenerate -m "description"

# Apply pending migrations
alembic upgrade head

# Check if migrations are up to date
alembic check
```

### Vector memory (Phase 4)

On Postgres, long-term memories live in `memory_vectors` (pgvector, 384 dims)
and every replica sees them. SQLite deployments keep the per-agent files in
`data/vectors/` and never create the table.

```bash
# One-time copy of old per-agent files, after `alembic upgrade head`
python scripts/migrate_vectors_to_pg.py --dry-run
python scripts/migrate_vectors_to_pg.py   # idempotent, keeps original ids

# Rollback without redeploying: falls back to the local SQLite files
AIOS_VECTOR_BACKEND=sqlite
```

Keep `data/vectors/` for one week after the switch; the copy preserves ids but
the SQLite files are the only rollback that does not need a DB restore.

## Coolify Deploy

1. Add service → Docker Compose
2. Paste `docker-compose.yml` contents
3. Set environment variables in Coolify UI
4. Mount `/data` volume for artifacts persistence
5. Deploy

## Monitoring

Health endpoints:
- `GET /health/live` — liveness probe (always 200 if process alive)
- `GET /health/ready` — readiness probe (checks DB connectivity)
- `GET /health` — full status (DB, scheduler, context cache)
- `GET /system/scheduler` — scheduler queue stats
- `GET /api/analytics/metrics` — in-memory counters
