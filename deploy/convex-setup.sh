#!/usr/bin/env bash
# Setup Convex deployment for AIOS
# This script configures the Convex project and deploys the schema
set -euo pipefail

BACKEND_URL="${1:-http://localhost:3210}"
DASHBOARD_URL="${2:-http://localhost:6791}"

echo "=== AIOS Convex Setup ==="
echo ""
echo "Backend: $BACKEND_URL"
echo "Dashboard: $DASHBOARD_URL"
echo ""

# Step 1: Configure convex project
echo "[1/3] Configuring Convex project..."
cd /root/ai_projects/claude_projects/pixor_aios/convex

# Create .env.local with backend URL
cat > .env.local << EOF
CONVEX_DEPLOY_KEY=
CONVEX_URL=$BACKEND_URL
EOF

echo "  Created .env.local"

# Step 2: Initialize project
echo "[2/3] Initializing project..."
if npx convex dev --once 2>&1; then
    echo "  Project initialized"
else
    echo "  WARNING: Init may have failed — check dashboard"
fi

# Step 3: Deploy schema
echo "[3/3] Deploying schema..."
if npx convex deploy 2>&1; then
    echo "  Schema deployed"
else
    echo "  Deploy failed — deploy manually via dashboard"
    echo "  Open: $DASHBOARD_URL"
    echo "  Then run: npx convex deploy"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Open dashboard: $DASHBOARD_URL"
echo "2. Get deploy key from Settings"
echo "3. Set in .env:"
echo "   AIOS_CONVEX_URL=$BACKEND_URL"
echo "   AIOS_CONVEX_ADMIN_KEY=<deploy-key>"
echo "   AIOS_DB_REPLICA_BACKEND=convex"
echo "4. Restart: docker compose up -d"
