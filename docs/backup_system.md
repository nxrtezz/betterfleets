# Backup System Documentation

## Overview

The betterfleet backup system provides comprehensive backup capabilities for:
- PostgreSQL database
- Media files (images, uploads, etc.)
- Configuration files (.env, docker-compose.yml, etc.)

## Management Commands

### Backup Command

Perform backups using the `backup` management command:

```bash
python manage.py backup [OPTIONS]
```

**Options:**
- `--type`: Type of backup to perform (choices: `all`, `database`, `media`, `config`, default: `all`)
- `--output-dir`: Output directory for backups (default: `BACKUP_DIR` from settings or `./backups`)
- `--compress`: Compress backup files with gzip
- `--verify`: Verify backup after creation

**Examples:**

```bash
# Backup everything with compression and verification
python manage.py backup --type all --compress --verify

# Backup only database
python manage.py backup --type database --compress

# Backup to specific directory
python manage.py backup --output-dir /mnt/backups/betterfleet --compress
```

### Restore Command

Restore from backup using the `restore` management command:

```bash
python manage.py restore backup_file [OPTIONS]
```

**Options:**
- `backup_file`: Path to backup file to restore (required)
- `--type`: Type of backup to restore (choices: `database`, `media`, `config`, required)
- `--force`: Skip confirmation prompt

**Examples:**

```bash
# Restore database from backup
python manage.py restore backups/database_20260531_120000.sql.gz --type database

# Restore media files
python manage.py restore backups/media_20260531_120000.tar.gz --type media

# Restore configuration
python manage.py restore backups/config_20260531_120000.tar.gz --type config --force
```

## Scheduled Backups

The `scheduled_backup.sh` script can be used for automated scheduled backups.

### Setup

1. Make the script executable:
```bash
chmod +x scripts/scheduled_backup.sh
```

2. Add to crontab for daily backups at 2 AM:
```bash
crontab -e
```

Add the following line:
```
0 2 * * * /app/scripts/scheduled_backup.sh >> /var/log/betterfleet_backup.log 2>&1
```

### Configuration

The script uses the `BACKUP_DIR` environment variable to determine where to store backups. Set this in your `.env` file:

```
BACKUP_DIR=/mnt/backups/betterfleet
```

If not set, backups will be stored in `./backups`.

### Cleanup

The script automatically cleans up backups older than 7 days. To change this, modify the `+7` value in the script.

## Backup File Naming

Backups are named with timestamps:
- Database: `database_YYYYMMDD_HHMMSS.sql` or `.sql.gz`
- Media: `media_YYYYMMDD_HHMMSS.tar` or `.tar.gz`
- Config: `config_YYYYMMDD_HHMMSS.tar` or `.tar.gz`

## Restore Procedures

### Database Restore

1. **Stop the application** to prevent conflicts:
```bash
docker-compose down
```

2. **Restore the database**:
```bash
python manage.py restore backups/database_20260531_120000.sql.gz --type database
```

3. **Restart the application**:
```bash
docker-compose up -d
```

### Media Restore

1. **Stop the application** (optional but recommended):
```bash
docker-compose down
```

2. **Restore media files**:
```bash
python manage.py restore backups/media_20260531_120000.tar.gz --type media
```

3. **Restart the application**:
```bash
docker-compose up -d
```

### Configuration Restore

1. **Restore configuration files**:
```bash
python manage.py restore backups/config_20260531_120000.tar.gz --type config
```

2. **Restart the application** for configuration changes to take effect:
```bash
docker-compose down
docker-compose up -d
```

## Disaster Recovery

### Complete System Restore

To restore the entire system from scratch:

1. **Restore configuration**:
```bash
python manage.py restore backups/config_20260531_120000.tar.gz --type config
```

2. **Restore database**:
```bash
python manage.py restore backups/database_20260531_120000.sql.gz --type database
```

3. **Restore media files**:
```bash
python manage.py restore backups/media_20260531_120000.tar.gz --type media
```

4. **Restart the application**:
```bash
docker-compose down
docker-compose up -d
```

### Docker Environment

For Docker deployments, ensure PostgreSQL is running before restoring the database:

```bash
docker-compose up -d postgres
# Wait for PostgreSQL to be ready
python manage.py restore backups/database_20260531_120000.sql.gz --type database
docker-compose up -d
```

## Backup Verification

The `--verify` option performs basic verification:
- Database: Checks that the backup file is not empty and contains valid SQL
- Media/Config: Uses `tar -t` to verify archive integrity

For more thorough verification, consider:
1. Restoring to a test environment
2. Checking database row counts before and after
3. Verifying critical data integrity

## Storage Considerations

- Compressed backups are recommended for production
- Monitor backup storage usage
- Implement off-site backup storage for disaster recovery
- Consider using S3 or similar for backup storage

## Security

- Backup files may contain sensitive data (passwords, API keys)
- Store backups securely with appropriate permissions
- Encrypt backups if stored off-site
- Restrict access to backup files and directories

## Troubleshooting

### Database Backup Fails

- Ensure PostgreSQL is running
- Check database connection settings in `.env`
- Verify pg_dump is installed and accessible
- Check disk space

### Restore Fails

- Ensure the backup file is not corrupted
- Check that the target service (PostgreSQL) is running
- Verify file permissions
- For database restore, ensure the database exists

### Permission Errors

- Run commands with appropriate permissions
- For Docker, ensure the container has access to the backup directory
- Check file ownership and permissions

## Settings

Add the following to your Django settings (optional):

```python
# Backup directory
BACKUP_DIR = os.environ.get("BACKUP_DIR", "./backups")
```

## Monitoring

Monitor backup success/failure by:
- Checking cron logs
- Monitoring backup directory for recent files
- Setting up alerts for failed backups
- Regularly testing restore procedures
