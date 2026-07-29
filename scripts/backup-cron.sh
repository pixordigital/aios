#!/bin/bash
# Add backup cron job — runs daily at 3am
# Usage: ./scripts/backup-cron.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_SCRIPT="$SCRIPT_DIR/backup.sh"

# Add cron if not already present
if ! crontab -l 2>/dev/null | grep -q "backup.sh"; then
    (crontab -l 2>/dev/null; echo "0 3 * * * $BACKUP_SCRIPT /root/aios-backups >> /var/log/aios-backup.log 2>&1") | crontab -
    echo "Backup cron added: daily at 3am"
else
    echo "Backup cron already exists"
fi

# Show current crontab
echo ""
echo "Current crontab:"
crontab -l 2>/dev/null || echo "(empty)"
