#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  AIOS_RESTORE_DRILL_TARGET_URL=<isolated-db-url> \
  AIOS_RESTORE_DRILL_CONFIRM=I_UNDERSTAND_THIS_IS_ISOLATED \
  deploy/restore_drill.sh <backup-file> [--report <path>] [--keep-db]

Safe restore drill into an ISOLATED temp/test DB. Never production.

Supported backup formats:
  - Postgres: *.sql.gz (plain pg_dump gzip, as produced by deploy/backup.sh)
  - SQLite:   *.db, *.sqlite, *.sqlite3, or gzipped sqlite file

Safety (fail-closed):
  - target URL required
  - confirmation token required
  - target must not equal AIOS_DATABASE_URL / DATABASE_URL
  - target DB name/path must contain drill/restore_test/restore-drill/tmp_restore/smoke_restore
  - refuses obvious prod hosts/names (prod, production, primary, live)

Verification:
  - artifact: sha256, size, gzip integrity when applicable
  - Postgres: restore into target, table counts, alembic_version read when present
  - SQLite: PRAGMA integrity_check + foreign_key_check on restored temp copy

Evidence:
  - writes JSON report (default: <backup>.restore-drill-report.json)
USAGE
}

die() { echo "restore_drill: $*" >&2; exit 1; }
log() { echo "restore_drill: $*" >&2; }

REPORT=""
KEEP_DB=0
BACKUP=""
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --report) [ $# -ge 2 ] || die "--report requires path"; REPORT="$2"; shift 2 ;;
    --keep-db) KEEP_DB=1; shift ;;
    --*) die "unknown arg: $1" ;;
    *) [ -z "$BACKUP" ] || die "unexpected arg: $1"; BACKUP="$1"; shift ;;
  esac
done

[ -n "$BACKUP" ] || { usage >&2; die "backup file required"; }
[ -f "$BACKUP" ] || die "backup file not found: $BACKUP"

TARGET="${AIOS_RESTORE_DRILL_TARGET_URL:-${RESTORE_DRILL_TARGET_URL:-}}"
[ -n "$TARGET" ] || die "AIOS_RESTORE_DRILL_TARGET_URL required (isolated DB only)"

CONFIRM="${AIOS_RESTORE_DRILL_CONFIRM:-}"
[ "$CONFIRM" = "I_UNDERSTAND_THIS_IS_ISOLATED" ] || \
  die "set AIOS_RESTORE_DRILL_CONFIRM=I_UNDERSTAND_THIS_IS_ISOLATED"

PROD_URL="${AIOS_DATABASE_URL:-${DATABASE_URL:-}}"
normalize_url() {
  printf '%s' "$1" | sed -E 's/[[:space:]]+$//; s#/$##'
}
if [ -n "$PROD_URL" ] && [ "$(normalize_url "$TARGET")" = "$(normalize_url "$PROD_URL")" ]; then
  die "target equals configured database URL; refusing"
fi

TARGET_LC=$(printf '%s' "$TARGET" | tr '[:upper:]' '[:lower:]')
if printf '%s' "$TARGET_LC" | grep -Eq '(prod|production|primary|live|main\.supabase\.co|neon\.tech/.+[^drill])'; then
  # allow only if name also clearly marked drill; still conservative
  if ! printf '%s' "$TARGET_LC" | grep -Eq '(drill|restore_test|restore-drill|tmp_restore|smoke_restore)'; then
    die "target looks unsafe/prod-like; refusing"
  fi
fi
if ! printf '%s' "$TARGET_LC" | grep -Eq '(drill|restore_test|restore-drill|tmp_restore|smoke_restore)'; then
  die "target DB name/path must contain drill/restore_test/restore-drill/tmp_restore/smoke_restore"
fi

command -v python3 >/dev/null 2>&1 || die "python3 required"

[ -n "$REPORT" ] || REPORT="${BACKUP}.restore-drill-report.json"
REPORT_DIR=$(dirname "$REPORT")
mkdir -p "$REPORT_DIR"

TMPDIR_DRILL=$(mktemp -d "${TMPDIR:-/tmp}/aios-restore-drill.XXXXXX")
cleanup() {
  if [ "$KEEP_DB" -eq 0 ]; then
    rm -rf "$TMPDIR_DRILL"
  else
    log "keeping temp dir: $TMPDIR_DRILL"
  fi
}
trap cleanup EXIT

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else python3 - "$1" <<'PY'
import hashlib,sys
p=sys.argv[1]; h=hashlib.sha256()
with open(p,'rb') as f:
    for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
print(h.hexdigest())
PY
  fi
}

SIZE_BYTES=$(wc -c < "$BACKUP" | tr -d ' ')
SHA=$(sha256 "$BACKUP")
START_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

is_sqlite=0
is_postgres=0
case "$BACKUP" in
  *.sql.gz|*.sql) is_postgres=1 ;;
  *.db|*.sqlite|*.sqlite3) is_sqlite=1 ;;
  *.db.gz|*.sqlite.gz|*.sqlite3.gz) is_sqlite=1 ;;
  *) 
    if gzip -t "$BACKUP" >/dev/null 2>&1; then
      if gunzip -c "$BACKUP" | head -c 64 | grep -qi 'sqlite format 3'; then is_sqlite=1
      else is_postgres=1; fi
    elif head -c 16 "$BACKUP" | grep -q 'SQLite format 3'; then is_sqlite=1
    else die "unsupported backup format: $BACKUP"
    fi
    ;;
esac

STATUS="failed"
CHECKS_JSON="[]"
ERROR=""
RPO_NOTE="operator: record backup age vs incident window"
RTO_SECONDS=""

run_python_report() {
  python3 - "$REPORT" "$BACKUP" "$SHA" "$SIZE_BYTES" "$START_TS" "$TARGET_LC" "$STATUS" "$ERROR" "$RTO_SECONDS" "$RPO_NOTE" "$CHECKS_JSON" <<'PY'
import json,sys,datetime
report,backup,sha,size,start,target,status,error,rto,rpo,checks = sys.argv[1:12]
doc={
  "schema":"aios.restore_drill.v1",
  "timestamp_utc":datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat().replace('+00:00','Z'),
  "started_utc":start,
  "backup_file":backup,
  "backup_sha256":sha,
  "backup_size_bytes":int(size),
  "target_redacted": target.split('@')[-1] if '@' in target else target,
  "status":status,
  "error":error or None,
  "rto_seconds": float(rto) if rto else None,
  "rpo_note":rpo,
  "checks":json.loads(checks),
  "operator_signoff":{"operator":"","approved":False,"notes":""},
}
with open(report,'w',encoding='utf-8') as f: json.dump(doc,f,indent=2,sort_keys=True); f.write('\n')
print(report)
PY
}

add_check() {
  local name="$1" ok="$2" detail="$3"
  CHECKS_JSON=$(python3 - "$CHECKS_JSON" "$name" "$ok" "$detail" <<'PY'
import json,sys
checks=json.loads(sys.argv[1])
checks.append({"name":sys.argv[2],"ok":sys.argv[3]=="true","detail":sys.argv[4]})
print(json.dumps(checks))
PY
)
}

finish() {
  local rc=$?
  if [ $rc -ne 0 ] && [ "$STATUS" != "passed" ]; then
    [ -n "$ERROR" ] || ERROR="restore drill failed (exit $rc)"
  fi
  END_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || python3 - <<'PY'
import datetime
print(datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ'))
PY
)
  RTO_SECONDS=$(python3 - "$START_TS" "$END_TS" <<'PY'
import sys,datetime
fmt='%Y-%m-%dT%H:%M:%SZ'
a=datetime.datetime.strptime(sys.argv[1],fmt).replace(tzinfo=datetime.UTC)
b=datetime.datetime.strptime(sys.argv[2],fmt).replace(tzinfo=datetime.UTC)
print(max(0,int((b-a).total_seconds())))
PY
)
  run_python_report >/dev/null || true
  log "report: $REPORT"
  echo "EVIDENCE_REPORT=$REPORT"
  exit $rc
}
trap finish EXIT

log "backup=$BACKUP size=$SIZE_BYTES sha256=$SHA"
add_check "backup_exists" true "$BACKUP"
add_check "backup_sha256" true "$SHA"
if [ "$SIZE_BYTES" -lt 100 ]; then
  add_check "backup_size" false "size < 100 bytes"
  die "backup too small: $SIZE_BYTES bytes"
fi
add_check "backup_size" true "$SIZE_BYTES bytes"

if [ "$is_postgres" -eq 1 ]; then
  command -v psql >/dev/null 2>&1 || die "psql required for postgres restore drill"
  if printf '%s' "$BACKUP" | grep -Eq '\.gz$'; then
    gzip -t "$BACKUP" || die "gzip integrity check failed"
    add_check "gzip_integrity" true "ok"
  fi
  # Optional pg_restore --list for custom/tar formats
  if printf '%s' "$BACKUP" | grep -Eq '\.(dump|tar|custom)$'; then
    command -v pg_restore >/dev/null 2>&1 || die "pg_restore required for custom/tar backup"
    pg_restore -l "$BACKUP" >/dev/null
    add_check "pg_restore_list" true "ok"
  else
    add_check "pg_restore_list" true "skipped (plain sql format)"
  fi

  log "restoring postgres backup into isolated target"
  RESTORE_LOG="$TMPDIR_DRILL/restore.log"
  if printf '%s' "$BACKUP" | grep -Eq '\.gz$'; then
    gunzip -c "$BACKUP" | psql "$TARGET" -v ON_ERROR_STOP=1 >"$RESTORE_LOG" 2>&1 || { tail -n 40 "$RESTORE_LOG" >&2 || true; die "psql restore failed"; }
  else
    psql "$TARGET" -v ON_ERROR_STOP=1 -f "$BACKUP" >"$RESTORE_LOG" 2>&1 || { tail -n 40 "$RESTORE_LOG" >&2 || true; die "psql restore failed"; }
  fi
  add_check "postgres_restore" true "psql ON_ERROR_STOP=1"

  SMOKE_SQL="SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1 LIMIT 50;"
  TABLES=$(psql "$TARGET" -At -c "$SMOKE_SQL" 2>"$TMPDIR_DRILL/smoke.err" || true)
  TABLE_COUNT=$(printf '%s\n' "$TABLES" | sed '/^$/d' | wc -l | tr -d ' ')
  [ "$TABLE_COUNT" -ge 1 ] || { cat "$TMPDIR_DRILL/smoke.err" >&2 || true; die "no public tables after restore"; }
  add_check "postgres_tables_present" true "count=$TABLE_COUNT"

  ALEMBIC_VER=$(psql "$TARGET" -At -c "SELECT version_num FROM alembic_version LIMIT 1;" 2>/dev/null || true)
  if [ -z "$ALEMBIC_VER" ]; then
    ALEMBIC_VER=$(psql "$TARGET" -At -c "SELECT version_num FROM aios.alembic_version_aios LIMIT 1;" 2>/dev/null || true)
  fi
  add_check "alembic_version_read" true "${ALEMBIC_VER:-missing}"

  CRITICAL_COUNTS=$(psql "$TARGET" -At -F= -c "
    SELECT 'organizations', count(*) FROM organizations
    UNION ALL SELECT 'users', count(*) FROM users
    UNION ALL SELECT 'agents', count(*) FROM agents;" 2>/dev/null || true)
  add_check "critical_table_counts" true "${CRITICAL_COUNTS:-skipped}"

  STATUS="passed"
  ERROR=""
  log "PASS postgres restore drill"
elif [ "$is_sqlite" -eq 1 ]; then
  command -v sqlite3 >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1 || die "sqlite3 or python3 required for sqlite restore drill"
  RESTORED_DB="$TMPDIR_DRILL/restored.sqlite"
  if printf '%s' "$BACKUP" | grep -Eq '\.gz$'; then
    gzip -t "$BACKUP" || die "gzip integrity check failed"
    add_check "gzip_integrity" true "ok"
    gunzip -c "$BACKUP" > "$RESTORED_DB"
  else
    cp "$BACKUP" "$RESTORED_DB"
  fi
  add_check "sqlite_restore_copy" true "$RESTORED_DB"

  sqlite_eval() {
    local db="$1" sql="$2"
    if command -v sqlite3 >/dev/null 2>&1; then
      sqlite3 "$db" "$sql"
    else
      python3 - "$db" "$sql" <<'PY'
import sqlite3,sys
db,sql=sys.argv[1],sys.argv[2]
conn=sqlite3.connect(db)
try:
    cur=conn.cursor(); cur.execute(sql)
    rows=cur.fetchall()
    if not rows:
        # pragma integrity_check returns row; empty means no rows
        pass
    for r in rows:
        print("|".join("" if v is None else str(v) for v in r))
finally:
    conn.close()
PY
    fi
  }

  INTEGRITY=$(sqlite_eval "$RESTORED_DB" 'PRAGMA integrity_check;')
  [ "$INTEGRITY" = "ok" ] || die "sqlite integrity_check failed: $INTEGRITY"
  add_check "sqlite_integrity_check" true "$INTEGRITY"

  FK_OUT=$(sqlite_eval "$RESTORED_DB" 'PRAGMA foreign_key_check;')
  [ -z "$FK_OUT" ] || die "sqlite foreign_key_check failed: $FK_OUT"
  add_check "sqlite_foreign_key_check" true "ok"

  TABLE_COUNT=$(sqlite_eval "$RESTORED_DB" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
  [ "$TABLE_COUNT" -ge 1 ] || die "no sqlite user tables after restore"
  add_check "sqlite_tables_present" true "count=$TABLE_COUNT"

  STATUS="passed"
  ERROR=""
  log "PASS sqlite restore drill"
else
  die "internal: unknown backup type"
fi
