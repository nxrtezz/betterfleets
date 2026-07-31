#!/bin/bash
# Scheduled backup script for betterfleet
# This script should be run via cron or similar scheduler

# Set environment
export PATH="/usr/local/bin:/usr/bin:/bin"
cd /app

# Activate virtual environment if needed
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Run backup
python manage.py backup --type all --compress --verify

# Clean up old backups (keep last 7 days)
BACKUP_DIR="${BACKUP_DIR:-./backups}"
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +7 -delete
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +7 -delete

echo "Backup completed at $(date)"
