# Production Configuration Guide

## Step 1: Required Environment Variables

Set these in your Coolify service or `.env` file:

### Database (Supabase PostgreSQL)
```bash
AIOS_DATABASE_URL="postgresql+asyncpg://aios:<password>@supabase-db:5432/aios"
AIOS_DB_BACKEND="sqlalchemy"
```

### Auth (Required)
```bash
AIOS_JWT_SECRET="<openssl rand -hex 32>"
AIOS_JWT_ALGORITHM="HS256"
AIOS_JWT_EXPIRE_MINUTES=60
AIOS_JWT_REFRESH_EXPIRE_DAYS=30
AIOS_ADMIN_MASTER_KEY="<openssl rand -hex 32>"
```

### Redis
```bash
AIOS_REDIS_URL="redis://redis:6379"
```

### LLM Provider (At least one)
```bash
# OpenRouter (recommended — supports all models)
AIOS_OPENROUTER_API_KEY="sk-or-..."

# Or direct OpenAI
AIOS_OPENAI_API_KEY="sk-..."

# Or direct Anthropic
AIOS_ANTHROPIC_API_KEY="sk-ant-..."
```

### Security
```bash
AIOS_DEBUG=false
AIOS_HTTPS_ONLY=true
AIOS_CORS_ORIGINS="https://aios.yourdomain.com"
AIOS_LOG_FORMAT="json"
AIOS_RATE_LIMIT_PER_MINUTE=60
```

### App URL
```bash
AIOS_APP_URL="https://aios.yourdomain.com"
AIOS_DASHBOARD_ENABLED=true
```

## Step 2: Optional Services

### Convex (Failover Database)
```bash
AIOS_DB_REPLICA_BACKEND="convex"
AIOS_CONVEX_URL="http://backend-xxx:3210"
AIOS_CONVEX_ADMIN_KEY="<from convex dashboard>"
```

### Supabase Storage (S3)
```bash
AIOS_STORAGE_BACKEND="s3"
AIOS_S3_ENDPOINT="http://supabase-kong:8000/storage/v1/s3"
AIOS_S3_BUCKET="aios-artifacts"
AIOS_S3_REGION="auto"
AIOS_S3_ACCESS_KEY="<supabase storage key>"
AIOS_S3_SECRET_KEY="<supabase storage secret>"
```

### Stripe Billing
```bash
AIOS_STRIPE_SECRET_KEY="sk_live_..."
AIOS_STRIPE_WEBHOOK_SECRET="whsec_..."
AIOS_STRIPE_PRICE_STARTER="price_..."
AIOS_STRIPE_PRICE_PRO="price_..."
```

### Email (SMTP)
```bash
AIOS_SMTP_HOST="smtp.resend.com"
AIOS_SMTP_PORT=587
AIOS_SMTP_USER="resend"
AIOS_SMTP_PASSWORD="<api-key>"
AIOS_SMTP_FROM_EMAIL="noreply@yourdomain.com"
```

### OAuth (Google)
```bash
AIOS_GOOGLE_CLIENT_ID="xxx.apps.googleusercontent.com"
AIOS_GOOGLE_CLIENT_SECRET="xxx"
```

### OAuth (GitHub)
```bash
AIOS_GITHUB_CLIENT_ID="xxx"
AIOS_GITHUB_CLIENT_SECRET="xxx"
```

### Error Tracking (Sentry)
```bash
AIOS_SENTRY_DSN="https://xxx@sentry.io/xxx"
```

## Step 3: Post-Deploy Checklist

```bash
# 1. Run migrations
docker compose exec app alembic upgrade head

# 2. Create admin account
curl -X POST https://your-domain/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@yourdomain.com","password":"<secure>","org_name":"Admin"}'

# 3. Make admin superadmin
docker compose exec app python -c "
import asyncio
from aios.db.engine import async_session
from aios.db.models import User
from sqlalchemy import select
async def make_superadmin():
    async with async_session() as db:
        user = (await db.execute(select(User).where(User.email == 'admin@yourdomain.com'))).scalar_one_or_none()
        if user:
            user.role = 'superadmin'
            await db.commit()
            print(f'Set {user.email} as superadmin')
asyncio.run(make_superadmin())
"

# 4. Test health
curl https://your-domain/health

# 5. Open dashboard
open https://your-domain/dashboard
```

## Step 4: Convex Schema Deploy

```bash
cd convex
npx convex deploy
```

## Step 5: Verify Everything

```bash
# Health check
curl https://your-domain/health

# Landing page
curl https://your-domain/

# Dashboard
curl https://your-domain/dashboard/login

# API docs
curl https://your-domain/docs
```
