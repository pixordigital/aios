#!/bin/bash
set -e
DATE=$(date +%Y%m%d_%H%M%S)
PGURL=${AIOS_DATABASE_URL:-postgresql://aios:aios@postgres:5432/aios}
BACKUP_DIR=/data/backups
mkdir -p $BACKUP_DIR
pg_dump "$PGURL" | gzip > $BACKUP_DIR/aios_$DATE.sql.gz
find $BACKUP_DIR -mtime +30 -delete
echo "backup $BACKUP_DIR/aios_$DATE.sql.gz ok"
