#!/bin/bash
# AIOS Database Backup Script with S3 Support
# Usage: ./scripts/backup-cron.sh [backup_dir]
# Backs up PostgreSQL database to SQL file with timestamp and optionally uploads to S3.
# Intended for cron: 0 2 * * * /path/to/scripts/backup-cron.sh /backups >> /var/log/aios-backup.log 2>&1

set -euo pipefail

BACKUP_DIR="${1:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/aios_${TIMESTAMP}.sql"

# S3 Configuration
S3_BUCKET="${AIOS_S3_BUCKET:-}"
S3_ENDPOINT="${AIOS_S3_ENDPOINT:-}"
S3_ACCESS_KEY="${AIOS_S3_ACCESS_KEY:-}"
S3_SECRET_KEY="${AIOS_S3_SECRET_KEY:-}"
S3_REGION="${AIOS_S3_REGION:-us-east-1}"
S3_PREFIX="${AIOS_S3_BACKUP_PREFIX:-aios/backups}"
S3_RETENTION_DAYS="${AIOS_S3_BACKUP_RETENTION_DAYS:-30}"

# Database URL
DATABASE_URL="${AIOS_DATABASE_URL:-}"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Extract connection info from DATABASE_URL
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
echo "Starting backup at $(date)..."
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
BACKUP_FILE_GZ="${BACKUP_FILE}.gz"

echo "Backup complete: ${BACKUP_FILE_GZ}"
echo "Size: $(du -h "${BACKUP_FILE_GZ}" | cut -f1)"

# Upload to S3 if configured
if [ -n "$S3_BUCKET" ] && [ -n "$S3_ACCESS_KEY" ] && [ -n "$S3_SECRET_KEY" ]; then
    echo "Uploading to S3..."
    
    AWS_CMD="aws s3"
    if [ -n "$S3_ENDPOINT" ]; then
        AWS_CMD="$AWS_CMD --endpoint-url $S3_ENDPOINT"
    fi
    AWS_CMD="$AWS_CMD --region $S3_REGION"
    
    # Export credentials for aws cli
    export AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY"
    export AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY"
    
    # Upload with SSE
    $AWS_CMD cp "$BACKUP_FILE_GZ" "s3://${S3_BUCKET}/${S3_PREFIX}/$(basename ${BACKUP_FILE_GZ})" \
        --server-side-encryption AES256 \
        --storage-class STANDARD_IA
    
    if [ $? -eq 0 ]; then
        echo "S3 upload successful: s3://${S3_BUCKET}/${S3_PREFIX}/$(basename ${BACKUP_FILE_GZ})"
    else
        echo "ERROR: S3 upload failed"
        exit 1
    fi
    
    # Clean old backups from S3 (retention policy)
    echo "Cleaning S3 backups older than ${S3_RETENTION_DAYS} days..."
    CUTOFF_DATE=$(date -d "-${S3_RETENTION_DAYS} days" +%Y-%m-%d)
    $AWS_CMD ls "s3://${S3_BUCKET}/${S3_PREFIX}/" --recursive | \
        awk -v cutoff="$CUTOFF_DATE" '$1 < cutoff {print $4}' | \
        while read -r key; do
            if [ -n "$key" ]; then
                $AWS_CMD rm "s3://${S3_BUCKET}/${key}"
                echo "Deleted old backup: s3://${S3_BUCKET}/${key}"
            fi
        done
else
    echo "S3 not configured, skipping upload"
fi

# Keep only last 7 local backups
ls -t "$BACKUP_DIR"/aios_*.sql.gz 2>/dev/null | tail -n +8 | xargs -r rm --

echo "Backups in $BACKUP_DIR: $(ls "$BACKUP_DIR"/aios_*.sql.gz 2>/dev/null | wc -l)"
echo "Backup job completed at $(date)"