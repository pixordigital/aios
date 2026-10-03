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
#
# set +e for this block: with `set -e` a failing bare `alembic ...` kills the
# shell instantly and the rc guards below never run -- the migration failure
# is silent and the container restart-loops with no error in its logs.
set +e
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
      # Reconcile, but ONLY for a genuinely un-stamped database.
      #
      # init_db() -> Base.metadata.create_all runs on every container start, so
      # a database created that way has no alembic_version row and replaying the
      # chain fails on the first already-existing table. That is the one case
      # where stamping head is correct.
      #
      # It is NOT correct when a version row exists and a revision genuinely
      # failed: stamping head there marks every pending revision as applied
      # without running it, and create_all never ALTERs an existing table, so
      # the release ships missing columns with a 200 from /health/ready and an
      # UndefinedColumnError on first use.
      # `alembic current` prints the applied revision, or nothing when the
      # database has no alembic_version row (schema came from create_all).
      # No inline python here: a heredoc inside $( ) inside `set +e` is a
      # silent-failure shape, and this only has to distinguish empty from not.
      _current=$(alembic current 2>/dev/null | tr -d '[:space:]')
      # "a0deb8aa39f7(head)" -> "a0deb8aa39f7"; "(head)" -> ""
      _current=${_current%%(*}
      if [ -z "$_current" ]; then
        _has_version=0
      else
        _has_version=1
      fi

      if [ "$_has_version" = "0" ]; then
        echo "[entrypoint] no alembic_version row (schema came from create_all); stamping head."
        alembic stamp head > /tmp/alembic_stamp.log 2>&1 || {
          echo "[entrypoint] FATAL: alembic stamp head failed."
          cat /tmp/alembic_stamp.log
          exit 1
        }
      else
        echo "[entrypoint] FATAL: migration failed on a stamped database (revision $_current)."
        echo "[entrypoint]        Refusing to stamp head — that would mark the failed revision"
        echo "[entrypoint]        applied without running it, leaving the schema incomplete."
        cat /tmp/alembic.log
        exit 1
      fi
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
set -e

exec "$@"
