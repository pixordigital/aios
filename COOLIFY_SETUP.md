# Coolify Deployment Guide

## Prerequisites
- Coolify installed on VPS
- Domain pointed to VPS IP (e.g., `aios.yourdomain.com`)
- Git repo connected to Coolify

## Services to Create in Coolify

### 1. PostgreSQL (Supabase)

If not already running Supabase, add a PostgreSQL service:

**Service Type:** PostgreSQL 15
**Internal Port:** 5432

Environment variables:
```
POSTGRES_DB=aios
POSTGRES_USER=aios
POSTGRES_PASSWORD=<generate-strong-password>
```

**Note:** If using Supabase's managed PostgreSQL, skip this — use their connection string.

### 2. Redis

**Service Type:** Redis 7
**Internal Port:** 6379

No password needed for internal Docker network.

### 3. Convex (Optional — for real-time features)

If deploying Convex separately:
- Create a Convex project at [convex.dev](https://convex.dev)
- Deploy schema: `cd convex && npx convex deploy`
- Note the `CONVEX_URL` and `ADMIN_KEY` from project settings

### 4. AIOS App (Main Service)

**Service Type:** Docker Compose
**Source:** Git repository

#### Docker Compose for Coolify:

```yaml
# docker-compose.coolify.yml
services:
  app:
    build: .
    ports:
      - "8777:8777"
    environment:
      # ─── Core ───
      AIOS_DEBUG: "false"
      AIOS_APP_NAME: "AIOS"
      AIOS_APP_URL: "https://aios.yourdomain.com"
      AIOS_LOG_FORMAT: "json"
      AIOS_DASHBOARD_ENABLED: "true"

      # ─── Database (Supabase/PostgreSQL) ───
      AIOS_DATABASE_URL: "postgresql+asyncpg://aios:<password>@postgres:5432/aios"
      AIOS_DB_BACKEND: "sqlalchemy"
      AIOS_DB_REPLICA_BACKEND: "convex"

      # ─── Convex (Failover) ───
      AIOS_CONVEX_URL: "https://your-project.convex.cloud"
      AIOS_CONVEX_ADMIN_KEY: "<your-admin-key>"

      # ─── Redis ───
      AIOS_REDIS_URL: "redis://redis:6379"

      # ─── Security ───
      AIOS_JWT_SECRET: "<generate-64-char-hex>"
      AIOS_JWT_ALGORITHM: "HS256"
      AIOS_JWT_EXPIRE_MINUTES: "60"
      AIOS_JWT_REFRESH_EXPIRE_DAYS: "30"
      AIOS_HTTPS_ONLY: "true"
      AIOS_CORS_ORIGINS: "https://aios.yourdomain.com"
      AIOS_RATE_LIMIT_PER_MINUTE: "60"
      AIOS_ADMIN_MASTER_KEY: "<generate-64-char-hex>"

      # ─── LLM Providers ───
      AIOS_OPENROUTER_API_KEY: "<your-key>"
      AIOS_OPENAI_API_KEY: "<your-key>"

      # ─── Storage ───
      AIOS_STORAGE_BACKEND: "s3"
      AIOS_S3_ENDPOINT: "https://<project>.supabase.co/storage/v1/s3"
      AIOS_S3_BUCKET: "aios-artifacts"
      AIOS_S3_REGION: "auto"
      AIOS_S3_ACCESS_KEY: "<supabase-key>"
      AIOS_S3_SECRET_KEY: "<supabase-secret>"

      # ─── Auth ───
      AIOS_GOOGLE_CLIENT_ID: "<google-client-id>"
      AIOS_GOOGLE_CLIENT_SECRET: "<google-client-secret>"
      AIOS_GITHUB_CLIENT_ID: "<github-client-id>"
      AIOS_GITHUB_CLIENT_SECRET: "<github-client-secret>"

      # ─── Email ───
      AIOS_SMTP_HOST: "smtp.resend.com"
      AIOS_SMTP_PORT: "587"
      AIOS_SMTP_USER: "resend"
      AIOS_SMTP_PASSWORD: "<resend-api-key>"
      AIOS_SMTP_FROM_EMAIL: "noreply@yourdomain.com"

      # ─── Billing ───
      AIOS_STRIPE_SECRET_KEY: "sk_live_<key>"
      AIOS_STRIPE_WEBHOOK_SECRET: "whsec_<secret>"
      AIOS_STRIPE_PRICE_STARTER: "price_<id>"
      AIOS_STRIPE_PRICE_PRO: "price_<id>"

      # ─── Monitoring ───
      AIOS_SENTRY_DSN: "https://<key>@sentry.io/<project>"

    volumes:
      - app-data:/data

    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8777/health/ready"]
      interval: 30s
      timeout: 10s
      start_period: 15s
      retries: 3

    restart: unless-stopped

  worker:
    build: .
    command: ["python", "-m", "aios.tasks.worker"]
    environment:
      AIOS_DATABASE_URL: "postgresql+asyncpg://aios:<password>@postgres:5432/aios"
      AIOS_REDIS_URL: "redis://redis:6379"
      AIOS_JWT_SECRET: "<same-as-app>"
    volumes:
      - app-data:/data
    restart: unless-stopped

volumes:
  app-data:
```

### 5. Caddy (Reverse Proxy)

**Service Type:** Docker Compose

```yaml
services:
  caddy:
    image: caddy:2-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy-data:/data
      - caddy-config:/config
    restart: unless-stopped

volumes:
  caddy-data:
  caddy-config:
```

**Caddyfile:**
```
aios.yourdomain.com {
    reverse_proxy app:8777

    request_body max_size 10MB

    @websocket {
        header Upgrade websocket
    }
    reverse_proxy @websocket app:8777

    header {
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        X-XSS-Protection "1; mode=block"
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        Referrer-Policy strict-origin-when-cross-origin
    }

    log {
        output stdout
        format json
    }
}

# Redirect HTTP to HTTPS
:80 {
    redir https://aios.yourdomain.com{uri}
}
```

## Coolify Configuration

### App Service Settings:

1. **Build Pack:** Docker Compose
2. **Compose File:** `docker-compose.coolify.yml`
3. **Port:** 8777
4. **Health Check Path:** `/health/ready`

### Environment Variables:

Copy all `AIOS_*` variables from the compose file above into Coolify's environment variables panel. **Never commit secrets to git.**

### Volumes:

Mount `/data` for artifact storage.

### Networking:

- App → PostgreSQL: Use Docker network (same compose stack)
- App → Redis: Use Docker network
- App → Convex: External (convex.cloud)
- Caddy → App: Internal network

## Post-Deploy Checklist

1. Run Alembic migrations:
   ```bash
   docker compose exec app alembic upgrade head
   ```

2. Create first admin user:
   ```bash
   curl -X POST https://aios.yourdomain.com/api/auth/register \
     -H "Content-Type: application/json" \
     -d '{"email":"admin@yourdomain.com","password":"<secure-password>","org_name":"Admin"}'
   ```

3. Set user as superadmin:
   ```sql
   UPDATE users SET role = 'superadmin' WHERE email = 'admin@yourdomain.com';
   ```

4. Configure Stripe webhooks:
   - URL: `https://aios.yourdomain.com/api/billing/stripe-webhook`
   - Events: `checkout.session.completed`, `invoice.paid`, `customer.subscription.deleted`

5. Configure WhatsApp webhooks (if using):
   - URL: `https://aios.yourdomain.com/webhook/whatsapp`
   - Verify token: Set in channel config

6. Test health:
   ```bash
   curl https://aios.yourdomain.com/health
   curl https://aios.yourdomain.com/health/ready
   ```

## Database Backups

### PostgreSQL (Supabase)
Supabase handles backups automatically. For manual:
```bash
docker compose exec postgres pg_dump -U aios aios > backup.sql
```

### Convex
Convex handles backups via their dashboard.

## Monitoring

- **Health:** `https://aios.yourdomain.com/health`
- **Readiness:** `https://aios.yourdomain.com/health/ready`
- **Scheduler:** `https://aios.yourdomain.com/system/scheduler`
- **Metrics:** `https://aios.yourdomain.com/api/analytics/metrics`
- **Dashboard:** `https://aios.yourdomain.com/dashboard`
- **API Docs:** `https://aios.yourdomain.com/docs`

## Troubleshooting

### App won't start
- Check logs: `docker compose logs app`
- Verify PostgreSQL is reachable: `docker compose exec app curl -sf http://postgres:5432`
- Verify Redis: `docker compose exec app redis-cli -h redis ping`

### Convex connection failed
- Check `AIOS_CONVEX_URL` and `AIOS_CONVEX_ADMIN_KEY`
- Verify Convex project is deployed: `cd convex && npx convex dashboard`

### Migration errors
- Run: `docker compose exec app alembic upgrade head`
- Check migration status: `docker compose exec app alembic history`

### Rate limiting not working
- Check Redis: `docker compose exec redis redis-cli ping`
- App falls back to in-memory if Redis unavailable
