#!/usr/bin/env bash
# AIOS Client Deploy — one-command setup for client VPS
set -euo pipefail

CLIENT_NAME="${1:-}"
CLIENT_EMAIL="${2:-}"
SUPERADMIN_KEY="${3:-}"  # Your master key so you can admin their instance

if [[ -z "$CLIENT_NAME" || -z "$CLIENT_EMAIL" ]]; then
    echo "Usage: curl -sL https://deploy.pixor.ai/deploy.sh | bash -s -- <client-name> <admin-email> [superadmin-key]"
    echo ""
    echo "  client-name     — e.g. 'AcmeCorp'"
    echo "  admin-email     — their admin email for login"
    echo "  superadmin-key  — YOUR master API key for remote admin (optional)"
    exit 1
fi

CLIENT_SLUG=$(echo "$CLIENT_NAME" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
PASS=$(openssl rand -base64 16)
JWT_SECRET=$(openssl rand -hex 32)

echo "=== AIOS Deploy for $CLIENT_NAME ==="
echo ""

# ─── Prerequisites ───
echo "[1/6] Installing prerequisites..."
apt-get update -qq && apt-get install -y -qq docker.io docker-compose curl >/dev/null 2>&1

# ─── DB (Supabase or PostgreSQL) ───
# If SUPABASE_URL env var exists, use it; otherwise prompt or use Docker Postgres
if [[ -z "${SUPABASE_URL:-}" ]]; then
    echo "[2/6] Starting local PostgreSQL..."
    docker run -d --name aios-db \
        -e POSTGRES_DB=aios \
        -e POSTGRES_USER=aios \
        -e POSTGRES_PASSWORD="$PASS" \
        -p 5432:5432 \
        postgres:16-alpine >/dev/null 2>&1
    DATABASE_URL="postgresql+asyncpg://aios:$PASS@localhost:5432/aios"
else
    DATABASE_URL="$SUPABASE_URL"
fi

# ─── AIOS Container ───
echo "[3/6] Starting AIOS..."
docker run -d --name aios \
    -p 8777:8777 \
    -e AIOS_DATABASE_URL="$DATABASE_URL" \
    -e AIOS_JWT_SECRET="$JWT_SECRET" \
    -e AIOS_OPENROUTER_API_KEY="${OPENROUTER_KEY:-}" \
    -e AIOS_APP_URL="http://$(curl -s ifconfig.me):8777" \
    -v aios-data:/data \
    --restart unless-stopped \
    pixordigital/aios:latest >/dev/null 2>&1

echo "[4/6] Waiting for startup..."
sleep 5

# ─── Register admin account ───
echo "[5/6] Creating admin account..."
REG=$(curl -s -X POST http://localhost:8777/dashboard/register \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "name=Admin&email=$CLIENT_EMAIL&password=$PASS&org_name=$CLIENT_NAME")

echo "[6/6] Setup complete!"
echo ""
echo "=== $CLIENT_NAME AIOS is LIVE ==="
echo ""
echo "  URL:       http://$(curl -s ifconfig.me):8777"
echo "  Login:     $CLIENT_EMAIL"
echo "  Password:  $PASS"
echo ""

# ─── Grant superadmin access to you ───
if [[ -n "$SUPERADMIN_KEY" ]]; then
    curl -s -X POST "http://localhost:8777/api/admin/register-remote" \
        -H "Content-Type: application/json" \
        -d "{\"key\": \"$SUPERADMIN_KEY\", \"org\": \"$CLIENT_NAME\"}" >/dev/null
    echo "  Remote admin: enabled"
fi

# Save credentials
cat > "/root/aios-${CLIENT_SLUG}-credentials.txt" << CRED
AIOS CLIENT: $CLIENT_NAME
URL: http://$(curl -s ifconfig.me):8777
ADMIN: $CLIENT_EMAIL
PASS: $PASS
JWT_SECRET: $JWT_SECRET
CRED

echo ""
echo "  Credentials saved to: /root/aios-${CLIENT_SLUG}-credentials.txt"
echo ""
echo "=== DONE ==="
