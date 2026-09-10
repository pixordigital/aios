#!/usr/bin/env bash
# Kokoro TTS smoke — 8GB VPS, CPU, no LiveKit
# Usage: ./scripts/voice-smoke.sh [base_url]
# Requires: curl, jq (optional)
set -e
APP_URL=${1:-http://localhost:8777}
KOKORO_INTERNAL="http://voice-tts-kokoro:8880"
# try host first (if ports exposed), fallback to docker exec
APP_CONTAINER=$(docker ps --format "{{.Names}}" 2>/dev/null | grep "app-38908" | head -1)
if [ -z "$APP_CONTAINER" ]; then APP_CONTAINER=$(docker ps --format "{{.Names}}" 2>/dev/null | grep "app" | head -1); fi

echo "=== app health ==="
curl -s "$APP_URL/health/live" | head -5
curl -s "$APP_URL/health/ready" | head -10
echo
echo "=== evolution ==="
curl -s http://localhost:8080/ | head -10
echo
echo "=== litellm ==="
curl -s http://localhost:4000/health/liveliness | head -5
echo
echo "=== kokoro health (internal) ==="
if [ -n "$APP_CONTAINER" ]; then
  docker exec "$APP_CONTAINER" curl -s "$KOKORO_INTERNAL/health" || echo "kokoro health via app failed"
  echo
  echo "=== kokoro models ==="
  docker exec "$APP_CONTAINER" curl -s "$KOKORO_INTERNAL/v1/models" | head -c 300; echo
  echo
  echo "=== kokoro voices (72 expected) ==="
  docker exec "$APP_CONTAINER" curl -s "$KOKORO_INTERNAL/v1/audio/voices" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"voices={len(d['voices'])} default={d['default_voice']}\")"
  echo
  echo "=== kokoro TTS 1-char smoke (af_heart) ==="
  docker exec "$APP_CONTAINER" bash -c 'curl -m 30 -s -w "CODE:%{http_code} SIZE:%{size_download}\n" -X POST http://voice-tts-kokoro:8880/v1/audio/speech -H "Content-Type: application/json" -d "{\"model\":\"kokoro\",\"input\":\"Hello\",\"voice\":\"af_heart\"}" -o /tmp/smoke.wav; echo "exit:$?"; ls -lh /tmp/smoke.wav 2>&1 | head -3'
  echo
  echo "=== kokoro pt voice pm_alex smoke ==="
  docker exec "$APP_CONTAINER" bash -c 'curl -m 30 -s -w "CODE:%{http_code} SIZE:%{size_download}\n" -X POST http://voice-tts-kokoro:8880/v1/audio/speech -H "Content-Type: application/json" -d "{\"model\":\"kokoro\",\"input\":\"Ola\",\"voice\":\"pm_alex\"}" -o /tmp/smoke_pt.wav; echo "exit:$?"; ls -lh /tmp/smoke_pt.wav 2>&1 | head -3'
  echo
  echo "=== livekit check (should be none) ==="
  docker ps --format "{{.Names}}" | grep -i livekit || echo "no livekit - OK"
  echo
  echo "=== app env ==="
  docker exec "$APP_CONTAINER" env | grep -E "VOICE_TTS|VOICE_ENGINE|KOKORO" | head -10
else
  echo "no app container found, skipping internal checks"
fi
echo
echo "=== docker compose config (kokoro) ==="
docker compose -f docker-compose.coolify.yml config --services | grep kokoro || echo "kokoro not in default services (expected, internal)"
docker compose -f docker-compose.coolify.yml config | grep -A2 "voice-tts-kokoro" | head -10
echo
echo "smoke done"
