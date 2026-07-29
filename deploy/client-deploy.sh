#!/usr/bin/env bash
# AIOS Client Deploy — one-command setup for client VPS
# Usage: ./deploy/client-deploy.sh <client-name> <admin-email> [superadmin-key]
set -euo pipefail

CLIENT_NAME="${1:-}"
CLIENT_EMAIL="${2:-}"
SUPERADMIN_KEY="${3:-}"

if [[ -z "$CLIENT_NAME" || -z "$CLIENT_EMAIL" ]]; then
    echo "Usage: ./deploy/client-deploy.sh <client-name> <admin-email> [superadmin-key]"
    echo ""
    echo "  client-name     — e.g. 'AcmeCorp'"
    echo "  admin-email     — their admin email for login"
    echo "  superadmin-key  — YOUR master key for remote admin (optional)"
    exit 1
fi

CLIENT_SLUG=$(echo "$CLIENT_NAME" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
PASS=$(openssl rand -base64 16)
JWT_SECRET=$(openssl rand -hex 32)
MASTER_KEY=$(openssl rand -hex 32)

echo "=== AIOS Deploy for $CLIENT_NAME ==="
echo ""

# ─── Prerequisites ───
echo "[1/8] Installing prerequisites..."
apt-get update -qq && apt-get install -y -qq docker.io docker-compose curl >/dev/null 2>&1

# ─── PostgreSQL ───
echo "[2/8] Starting PostgreSQL..."
docker run -d --name aios-db \
    -e POSTGRES_DB=aios \
    -e POSTGRES_USER=aios \
    -e POSTGRES_PASSWORD="$PASS" \
    -p 5432:5432 \
    postgres:16-alpine >/dev/null 2>&1
DATABASE_URL="postgresql+asyncpg://aios:$PASS@localhost:5432/aios"

# ─── Redis ───
echo "[3/8] Starting Redis..."
docker run -d --name aios-redis \
    -p 6379:6379 \
    redis:7-alpine >/dev/null 2>&1

# ─── AIOS Container ───
echo "[4/8] Starting AIOS..."
PUBLIC_IP=$(curl -s ifconfig.me)
docker run -d --name aios \
    -p 8777:8777 \
    -e AIOS_DATABASE_URL="$DATABASE_URL" \
    -e AIOS_JWT_SECRET="$JWT_SECRET" \
    -e AIOS_ADMIN_MASTER_KEY="$MASTER_KEY" \
    -e AIOS_REDIS_URL="redis://localhost:6379" \
    -e AIOS_OPENROUTER_API_KEY="${OPENROUTER_KEY:-}" \
    -e AIOS_APP_URL="http://$PUBLIC_IP:8777" \
    -e AIOS_DEBUG=false \
    -e AIOS_LOG_FORMAT=json \
    -v aios-data:/data \
    --restart unless-stopped \
    pixordigital/aios:latest >/dev/null 2>&1

echo "[5/8] Waiting for startup..."
sleep 8

# ─── Run migrations ───
echo "[6/8] Running database migrations..."
docker exec aios python -c "
import asyncio
from aios.db.engine import init_db
asyncio.run(init_db())
print('Tables created')
" 2>/dev/null || echo "Migration note: tables may need manual creation"

# ─── Register admin account ───
echo "[7/8] Creating admin account..."
curl -s -X POST http://localhost:8777/api/auth/register \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$CLIENT_EMAIL\",\"password\":\"$PASS\",\"org_name\":\"$CLIENT_NAME\"}" >/dev/null

# Make superadmin
docker exec aios python -c "
import asyncio
from aios.db.engine import async_session
from aios.db.models import User
from sqlalchemy import select
async def make_superadmin():
    async with async_session() as db:
        user = (await db.execute(select(User).where(User.email == '$CLIENT_EMAIL'))).scalar_one_or_none()
        if user:
            user.role = 'superadmin'
            user.email_verified = True
            await db.commit()
asyncio.run(make_superadmin())
" 2>/dev/null

# ─── Grant remote admin access ───
if [[ -n "$SUPERADMIN_KEY" ]]; then
    echo "[8/8] Enabling remote admin..."
    curl -s -X POST "http://localhost:8777/api/admin/register-remote" \
        -H "Content-Type: application/json" \
        -d "{\"key\": \"$SUPERADMIN_KEY\", \"org_name\": \"$CLIENT_NAME\"}" >/dev/null
    echo "  Remote admin: enabled"
else
    echo "[8/8] Skipping remote admin (no key provided)"
fi

echo ""
echo "=== $CLIENT_NAME AIOS is LIVE ==="
echo ""
echo "  URL:          http://$PUBLIC_IP:8777"
echo "  Dashboard:    http://$PUBLIC_IP:8777/dashboard"
echo "  Landing:      http://$PUBLIC_IP:8777/"
echo "  Login:        $CLIENT_EMAIL"
echo "  Password:     $PASS"
echo "  Master Key:   $MASTER_KEY"
echo ""

# Save credentials
cat > "/root/aios-${CLIENT_SLUG}-credentials.txt" << CRED
AIOS CLIENT: $CLIENT_NAME
URL: http://$PUBLIC_IP:8777
DASHBOARD: http://$PUBLIC_IP:8777/dashboard
ADMIN: $CLIENT_EMAIL
PASSWORD: $PASS
JWT_SECRET: $JWT_SECRET
MASTER_KEY: $MASTER_KEY
DATABASE_URL: $DATABASE_URL
CRED

echo "  Credentials saved to: /root/aios-${CLIENT_SLUG}-credentials.txt"
echo ""
echo "=== NEXT STEPS ==="
echo ""
echo "  1. Set AIOS_* env vars for production features (see PRODUCTION_CONFIG.md)"
echo "  2. Configure Stripe billing (if selling subscriptions)"
echo "  3. Configure SMTP (for email verification/password reset)"
echo "  4. Set up HTTPS (Cloudflare or Caddy)"
echo "  5. Deploy Convex schema: cd convex && npx convex deploy"
echo ""
echo "=== DONE ==="
