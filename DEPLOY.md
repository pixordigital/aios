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

## Coolify Deploy

1. Add service → Docker Compose
2. Paste `docker-compose.yml` contents
3. Set environment variables in Coolify UI
4. Mount `/data` volume for artifacts persistence
5. Deploy

## Convex Deploy (Optional Failover Backend)

```bash
cd convex
npx convex dev --configure=existing
# Then set AIOS_CONVEX_URL + AIOS_CONVEX_ADMIN_KEY in .env
```

## Monitoring

Health endpoints:
- `GET /health/live` — liveness probe (always 200 if process alive)
- `GET /health/ready` — readiness probe (checks DB connectivity)
- `GET /health` — full status (DB, scheduler, context cache)
- `GET /system/scheduler` — scheduler queue stats
- `GET /api/analytics/metrics` — in-memory counters
