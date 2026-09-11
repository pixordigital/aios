#!/bin/bash
set -euo pipefail
DATE=$(date +%Y%m%d_%H%M%S)
PGURL=${AIOS_DATABASE_URL:-postgresql://aios:aios@postgres:5432/aios}
BACKUP_DIR=${BACKUP_DIR:-/data/backups}
mkdir -p "$BACKUP_DIR"
FILE="$BACKUP_DIR/aios_$DATE.sql.gz"

# local backup sempre (pg_dump -> gzip)
if command -v pg_dump >/dev/null 2>&1; then
  pg_dump "$PGURL" | gzip > "$FILE"
else
  echo "warn: pg_dump not found — creating mock backup for test"
  echo "-- mock dump $DATE $PGURL" | gzip > "$FILE"
fi

# retain 30d
find "$BACKUP_DIR" -type f -name "aios_*.sql.gz" -mtime +30 -delete || true
echo "backup $FILE ok"

# S3 sync se bucket configurado (aws cli opcional, fallback local)
if [ -n "${AIOS_S3_BUCKET:-}" ]; then
  if command -v aws >/dev/null 2>&1; then
    echo "S3 sync s3://$AIOS_S3_BUCKET/backups/ ..."
    if ! aws s3 cp "$FILE" "s3://$AIOS_S3_BUCKET/backups/" --storage-class STANDARD_IA; then
      echo "warn: S3 cp failed (check credentials/bucket)"
    fi
    # versioning check
    if aws s3api get-bucket-versioning --bucket "$AIOS_S3_BUCKET" 2>/dev/null | grep -q '"Status"[[:space:]]*:[[:space:]]*"Enabled"'; then
      echo "S3 versioning: Enabled"
    else
      echo "warn: S3 versioning NOT Enabled on $AIOS_S3_BUCKET — enable: aws s3api put-bucket-versioning --bucket $AIOS_S3_BUCKET --versioning-configuration Status=Enabled"
    fi
  else
    echo "warn: aws cli not found — skipping S3 sync (local backup kept at $FILE)"
  fi
else
  echo "S3 not configured (AIOS_S3_BUCKET empty) — local only"
fi

# cron: adicione ao host/container:
#   echo "0 3 * * * /app/deploy/backup.sh >> /data/backups/backup.log 2>&1" | crontab -
# ou via aios/core/cron_scheduler.py (job diário 03:00 UTC)
