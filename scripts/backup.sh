#!/bin/bash
# AIOS Database Backup Script
# Usage: ./scripts/backup.sh [backup_dir]
# Backs up PostgreSQL database to SQL file with timestamp.

set -euo pipefail

BACKUP_DIR="${1:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/aios_${TIMESTAMP}.sql"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Extract connection info from DATABASE_URL
# Format: postgresql+asyncpg://user:password@host:5432/dbname
DATABASE_URL="${AIOS_DATABASE_URL:-}"

if [ -z "$DATABASE_URL" ]; then
    echo "ERROR: AIOS_DATABASE_URL not set"
    exit 1
fi

# Parse URL components
USER=$(echo "$DATABASE_URL" | sed -n 's|.*://\([^:]*\):.*|\1|p')
PASSWORD=$(echo "$DATABASE_URL" | sed -n 's|.*://[^:]*:\([^@]*\)@.*|\1|p')
HOST=$(echo "$DATABASE_URL" | sed -n 's|.*@\([^:]*\):.*|\1|p')
PORT=$(echo "$DATABASE_URL" | sed -n 's|.*:\([0-9]*\)/.*|\1|p')
DBNAME=$(echo "$DATABASE_URL" | sed -n 's|.*/\([^?]*\).*|\1|p')

# Run pg_dump
PGPASSWORD="$PASSWORD" pg_dump \
    -h "$HOST" \
    -p "$PORT" \
    -U "$USER" \
    -d "$DBNAME" \
    --no-owner \
    --no-privileges \
    -f "$BACKUP_FILE" \
    2>/dev/null

# Compress
gzip "$BACKUP_FILE"

# Keep only last 7 backups
ls -t "$BACKUP_DIR"/aios_*.sql.gz 2>/dev/null | tail -n +8 | xargs -r rm --

echo "Backup complete: ${BACKUP_FILE}.gz"
echo "Size: $(du -h "${BACKUP_FILE}.gz" | cut -f1)"
echo "Backups in $BACKUP_DIR: $(ls "$BACKUP_DIR"/aios_*.sql.gz 2>/dev/null | wc -l)"
