#!/usr/bin/env bash
# AIOS Client Deploy — simple, no Docker needed
set -euo pipefail

CLIENT_NAME="${1:-}"
CLIENT_EMAIL="${2:-}"

if [[ -z "$CLIENT_NAME" || -z "$CLIENT_EMAIL" ]]; then
    echo "Usage: bash client-deploy-simple.sh <client-name> <admin-email>"
    echo "  client-name  — e.g. 'AcmeCorp'"
    echo "  admin-email  — their admin email for login"
    exit 1
fi

PASS=$(openssl rand -base64 16)
JWT_SECRET=$(openssl rand -hex 32)

echo "=== AIOS Deploy for $CLIENT_NAME ==="

# Install deps
apt-get update -qq && apt-get install -y -qq python3 python3-pip git >/dev/null 2>&1

# Clone & setup
cd /opt
git clone https://github.com/pixordigital/aios.git
cd aios
pip3 install -e . 2>/dev/null
pip3 install gunicorn asyncpg 2>/dev/null

# .env
cat > .env << ENVEOF
AIOS_DATABASE_URL="sqlite+aiosqlite:///./aios.db"
AIOS_JWT_SECRET="$JWT_SECRET"
AIOS_OPENROUTER_API_KEY=""
AIOS_DEBUG=false
AIOS_APP_URL="http://$(curl -s ifconfig.me):8777"
ENVEOF

# Systemd service
cat > /etc/systemd/system/aios-client.service << SRVEOF
[Unit]
Description=AIOS Client - $CLIENT_NAME
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/aios
Environment=PYTHONUNBUFFERED=1
ExecStart=$(which gunicorn) aios.main:app \\
    --worker-class uvicorn.workers.UvicornWorker \\
    --bind 0.0.0.0:8777 \\
    --workers 2 --timeout 120 \\
    --access-logfile /var/log/aios-client.log \\
    --error-logfile /var/log/aios-client.log
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SRVEOF

systemctl daemon-reload
systemctl enable --now aios-client

sleep 3

# Register admin
curl -s -X POST http://localhost:8777/dashboard/register \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "name=Admin&email=$CLIENT_EMAIL&password=$PASS&org_name=$CLIENT_NAME" >/dev/null

echo ""
echo "=== $CLIENT_NAME AIOS LIVE ==="
echo "  URL:       http://$(curl -s ifconfig.me):8777"
echo "  Login:     $CLIENT_EMAIL"
echo "  Password:  $PASS"
echo ""

cat > /root/aios-${CLIENT_NAME}-creds.txt << CRED
CLIENT: $CLIENT_NAME
URL: http://$(curl -s ifconfig.me):8777
ADMIN: $CLIENT_EMAIL
PASS: $PASS
CRED
echo "Credentials: /root/aios-${CLIENT_NAME}-creds.txt"
