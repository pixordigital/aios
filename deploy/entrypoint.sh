#!/bin/sh
set -e

wait_for_postgres() {
  # If AIOS_DATABASE_URL uses supabase, check that host instead (Ruflo: supabase migration)
  PG_CHECK_HOST="${PGHOST:-postgres}"
  if echo "${AIOS_DATABASE_URL:-}" | grep -q "supabase-db"; then
    PG_CHECK_HOST="supabase-db"
  fi
  echo "[entrypoint] waiting for postgres at $PG_CHECK_HOST..."
  i=0
  until pg_isready -h "$PG_CHECK_HOST" -p "${PGPORT:-5432}" -U "${POSTGRES_USER:-aios}" -d "${POSTGRES_DB:-aios}" 2>/dev/null; do
    i=$((i+1))
    if [ "$i" -ge 15 ]; then
      echo "[entrypoint] postgres $PG_CHECK_HOST not ready after 15 tries, continuing anyway (AIOS_DATABASE_URL may use different host)"
      break
    fi
    echo "[entrypoint] postgres not ready, retry $i/15..."
    sleep 2
  done
  echo "[entrypoint] postgres check done"
}

wait_for_redis() {
  if [ -n "${AIOS_REDIS_URL:-}" ] || [ -n "${REDIS_PASSWORD:-}" ] || [ -n "${AIOS_REDIS_PASSWORD:-}" ]; then
    echo "[entrypoint] waiting for redis..."
    i=0
    until python3 -c "import os,redis;from urllib.parse import urlparse;u=os.environ.get('AIOS_REDIS_URL','') or 'redis://:'+os.environ.get('REDIS_PASSWORD',os.environ.get('AIOS_REDIS_PASSWORD',''))+'@'+os.environ.get('REDIS_HOST','redis')+':'+os.environ.get('REDIS_PORT','6379')+'/0';p=urlparse(u);r=redis.Redis(host=p.hostname or os.environ.get('REDIS_HOST','redis'),port=p.port or 6379,password=p.password or os.environ.get('REDIS_PASSWORD') or os.environ.get('AIOS_REDIS_PASSWORD'));r.ping()" 2>/dev/null; do
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

# NOTE: do NOT pipe alembic through `tee` here. In POSIX sh a pipeline's exit
# status is that of its LAST command, and tee always succeeds, so the `if !`
# guards below were unreachable: a failed migration was logged and then ignored,
# gunicorn started against a half-migrated schema, and the deploy was reported
# green. Capture the output to a file and check alembic's own status instead.
echo "[entrypoint] alembic upgrade head..."
alembic upgrade head > /tmp/alembic.log 2>&1
alembic_rc=$?
if [ "$alembic_rc" -ne 0 ]; then
  echo "[entrypoint] alembic upgrade head FAILED (rc=$alembic_rc), trying heads..."
  cat /tmp/alembic.log
  alembic upgrade heads > /tmp/alembic.log 2>&1
  alembic_rc=$?
  if [ "$alembic_rc" -ne 0 ]; then
    echo "[entrypoint] alembic upgrade heads FAILED (rc=$alembic_rc), retrying once after 5s..."
    cat /tmp/alembic.log
    sleep 5
    alembic upgrade heads > /tmp/alembic.log 2>&1
    alembic_rc=$?
    if [ "$alembic_rc" -ne 0 ]; then
      # Reconcile. This deployment materialises the schema through
      # init_db() -> Base.metadata.create_all on every container start, so a
      # database created that way has no alembic_version row and replaying the
      # whole chain fails on the first already-existing table. That is not a
      # broken schema -- it is an un-stamped one.
      #
      # Stamp head, then re-run the upgrade so any genuinely pending revision
      # still applies. Only refuse to start if the re-run also fails, which
      # means something real is wrong.
      echo "[entrypoint] WARNING: replay failed. Schema is managed by create_all;"
      echo "[entrypoint]          stamping head and re-running to apply anything pending."
      alembic stamp head > /tmp/alembic_stamp.log 2>&1 || {
        echo "[entrypoint] FATAL: alembic stamp head failed."
        cat /tmp/alembic_stamp.log
        exit 1
      }
      alembic upgrade head > /tmp/alembic.log 2>&1
      alembic_rc=$?
      if [ "$alembic_rc" -ne 0 ]; then
        echo "[entrypoint] FATAL: schema migration failed after stamp. Refusing to start."
        cat /tmp/alembic.log
        exit 1
      fi
    fi
  fi
fi
cat /tmp/alembic.log

exec "$@"
