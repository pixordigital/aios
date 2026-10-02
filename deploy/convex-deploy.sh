#!/usr/bin/env bash
# Deploy Convex schema for AIOS
# Usage: ./deploy/convex-deploy.sh [convex-backend-url]
set -euo pipefail

BACKEND_URL="${1:-http://localhost:3210}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONVEX_DIR="$SCRIPT_DIR/../convex"

echo "=== AIOS Convex Schema Deploy ==="
echo ""

# Check if convex CLI is available
if ! command -v npx &> /dev/null; then
    echo "ERROR: npx not found. Install Node.js first."
    exit 1
fi

# Check if convex directory exists
if [[ ! -d "$CONVEX_DIR" ]]; then
    echo "ERROR: convex/ directory not found at $CONVEX_DIR"
    exit 1
fi

echo "[1/3] Checking Convex backend at $BACKEND_URL..."
if curl -sf "$BACKEND_URL" > /dev/null 2>&1; then
    echo "  Backend reachable"
else
    echo "  WARNING: Backend not reachable at $BACKEND_URL"
    echo "  Continuing anyway..."
fi

echo "[2/3] Deploying schema..."
cd "$CONVEX_DIR"

# Try to deploy
if npx convex deploy 2>&1; then
    echo "  Schema deployed successfully"
else
    echo "  Deploy failed — trying with --configure..."
    npx convex deploy --configure=existing 2>&1 || {
        echo "ERROR: Convex deploy failed. Check convex/ directory and backend."
        exit 1
    }
fi

echo "[3/3] Verifying..."
if npx convex health 2>&1; then
    echo "  Convex healthy"
else
    echo "  WARNING: Health check failed"
fi

echo ""
echo "=== Convex Deploy Complete ==="
echo ""
echo "Update .env with:"
echo "  AIOS_CONVEX_URL=$BACKEND_URL"
echo "  AIOS_CONVEX_ADMIN_KEY=<from convex dashboard>"
echo "  AIOS_DB_REPLICA_BACKEND=convex"
echo ""
echo "Then restart: docker compose up -d"
