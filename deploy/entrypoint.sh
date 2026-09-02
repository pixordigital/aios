#!/bin/sh
set -e

wait_for_postgres() {
  echo "[entrypoint] waiting for postgres..."
  i=0
  until pg_isready -h "${PGHOST:-postgres}" -p "${PGPORT:-5432}" -U "${POSTGRES_USER:-aios}" -d "${POSTGRES_DB:-aios}" 2>/dev/null; do
    i=$((i+1))
    if [ "$i" -ge 30 ]; then
      echo "[entrypoint] postgres not ready after 30 tries, continuing anyway"
      break
    fi
    echo "[entrypoint] postgres not ready, retry $i/30..."
    sleep 2
  done
  echo "[entrypoint] postgres check done"
}

wait_for_redis() {
  if [ -n "${AIOS_REDIS_URL:-}" ] || [ -n "${REDIS_PASSWORD:-}" ]; then
    echo "[entrypoint] waiting for redis..."
    i=0
    until redis-cli -h "${REDIS_HOST:-redis}" -p "${REDIS_PORT:-6379}" -a "${REDIS_PASSWORD:-${AIOS_REDIS_PASSWORD:-}}" ping 2>/dev/null | grep -q PONG; do
      i=$((i+1))
      if [ "$i" -ge 15 ]; then
        echo "[entrypoint] redis not ready after 15 tries, continuing anyway"
        break
      fi
      echo "[entrypoint] redis not ready, retry $i/15..."
      sleep 2
    done
    echo "[entrypoint] redis check done"
  fi
}

if [ -z "${AIOS_JWT_SECRET:-}" ]; then
  echo "[entrypoint] FATAL: AIOS_JWT_SECRET not set — generate with: openssl rand -hex 32" >&2
  sleep 5
  exit 1
fi

wait_for_postgres
wait_for_redis

echo "[entrypoint] alembic upgrade head..."
if ! alembic upgrade head; then
  echo "[entrypoint] alembic failed, retrying once after 5s..."
  sleep 5
  alembic upgrade head || echo "[entrypoint] alembic still failed, starting app anyway (DB may already be migrated)"
fi

exec "$@"
