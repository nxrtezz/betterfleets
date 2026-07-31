import os
import subprocess
import shutil
import gzip
from datetime import datetime
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import connection


class Command(BaseCommand):
    help = "Perform backup of PostgreSQL database, media files, and configuration"

    def add_arguments(self, parser):
        parser.add_argument(
            "--type",
            choices=["all", "database", "media", "config"],
            default="all",
            help="Type of backup to perform",
        )
        parser.add_argument(
            "--output-dir",
            help="Output directory for backups (default: BACKUP_DIR from settings or ./backups)",
        )
        parser.add_argument(
            "--compress",
            action="store_true",
            help="Compress backup files with gzip",
        )
        parser.add_argument(
            "--verify",
            action="store_true",
            help="Verify backup after creation",
        )

    def handle(self, *args, **options):
        backup_type = options["type"]
        output_dir = Path(options.get("output_dir") or getattr(settings, "BACKUP_DIR", "./backups"))
        compress = options["compress"]
        verify = options["verify"]

        # Create output directory if it doesn't exist
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.stdout.write(f"Starting backup at {timestamp}")
        self.stdout.write(f"Output directory: {output_dir}")
        self.stdout.write(f"Backup type: {backup_type}")
        self.stdout.write(f"Compress: {compress}")
        self.stdout.write(f"Verify: {verify}")
        self.stdout.write("")

        if backup_type in ["all", "database"]:
            self.backup_database(output_dir, timestamp, compress, verify)

        if backup_type in ["all", "media"]:
            self.backup_media(output_dir, timestamp, compress, verify)

        if backup_type in ["all", "config"]:
            self.backup_config(output_dir, timestamp, compress, verify)

        self.stdout.write(self.style.SUCCESS("Backup completed successfully"))

    def backup_database(self, output_dir, timestamp, compress, verify):
        self.stdout.write("Backing up PostgreSQL database...")

        # Get database connection details
        db_config = settings.DATABASES["default"]
        db_name = db_config["NAME"]
        db_user = db_config["USER"]
        db_host = db_config["HOST"]
        db_port = db_config["PORT"]
        db_password = db_config["PASSWORD"]

        backup_file = output_dir / f"database_{timestamp}.sql"
        if compress:
            backup_file = output_dir / f"database_{timestamp}.sql.gz"

        try:
            # Build pg_dump command
            pg_dump_cmd = [
                "pg_dump",
                f"--dbname=postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}",
                "--no-owner",
                "--no-acl",
                "--format=plain",
            ]

            if compress:
                # Compress on the fly
                with open(backup_file, "wb") as f:
                    process = subprocess.Popen(
                        pg_dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                    with subprocess.Popen(
                        ["gzip"], stdin=process.stdout, stdout=f
                    ) as gzip_process:
                        process.wait()
                        gzip_process.wait()
            else:
                with open(backup_file, "w") as f:
                    subprocess.run(pg_dump_cmd, stdout=f, check=True)

            file_size = backup_file.stat().st_size
            self.stdout.write(
                self.style.SUCCESS(f"Database backup created: {backup_file} ({file_size} bytes)")
            )

            if verify:
                self.verify_database_backup(backup_file, compress)

        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f"Database backup failed: {e}"))
            raise
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Database backup error: {e}"))
            raise

    def verify_database_backup(self, backup_file, compress):
        self.stdout.write("Verifying database backup...")

        try:
            if compress:
                # Check if gzip file is valid
                with gzip.open(backup_file, "rt") as f:
                    # Read first few lines to verify it's valid SQL
                    lines = [f.readline() for _ in range(5)]
                    if not any(line for line in lines):
                        raise ValueError("Backup file appears to be empty")
            else:
                # Check if SQL file is valid
                with open(backup_file, "r") as f:
                    lines = [f.readline() for _ in range(5)]
                    if not any(line for line in lines):
                        raise ValueError("Backup file appears to be empty")

            self.stdout.write(self.style.SUCCESS("Database backup verification passed"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Database backup verification failed: {e}"))
            raise

    def backup_media(self, output_dir, timestamp, compress, verify):
        self.stdout.write("Backing up media files...")

        media_root = Path(getattr(settings, "MEDIA_ROOT", "./media"))
        if not media_root.exists():
            self.stdout.write(self.style.WARNING("Media directory does not exist, skipping"))
            return

        backup_file = output_dir / f"media_{timestamp}.tar"
        if compress:
            backup_file = output_dir / f"media_{timestamp}.tar.gz"

        try:
            if compress:
                subprocess.run(
                    ["tar", "-czf", str(backup_file), "-C", str(media_root.parent), media_root.name],
                    check=True,
                )
            else:
                subprocess.run(
                    ["tar", "-cf", str(backup_file), "-C", str(media_root.parent), media_root.name],
                    check=True,
                )

            file_size = backup_file.stat().st_size
            self.stdout.write(
                self.style.SUCCESS(f"Media backup created: {backup_file} ({file_size} bytes)")
            )

            if verify:
                self.verify_tar_backup(backup_file)

        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f"Media backup failed: {e}"))
            raise
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Media backup error: {e}"))
            raise

    def backup_config(self, output_dir, timestamp, compress, verify):
        self.stdout.write("Backing up configuration files...")

        config_files = [
            ".env",
            ".env.example",
            "docker-compose.yml",
            "docker-compose.override.yml",
            "Dockerfile",
            "gunicorn.conf.py",
            "pyproject.toml",
            "package.json",
        ]

        backup_file = output_dir / f"config_{timestamp}.tar"
        if compress:
            backup_file = output_dir / f"config_{timestamp}.tar.gz"

        base_dir = Path(settings.BASE_DIR)

        try:
            # Collect existing config files
            existing_files = []
            for config_file in config_files:
                config_path = base_dir / config_file
                if config_path.exists():
                    existing_files.append(str(config_path.name))

            if not existing_files:
                self.stdout.write(self.style.WARNING("No configuration files found, skipping"))
                return

            if compress:
                subprocess.run(
                    ["tar", "-czf", str(backup_file), "-C", str(base_dir)] + existing_files,
                    check=True,
                )
            else:
                subprocess.run(
                    ["tar", "-cf", str(backup_file), "-C", str(base_dir)] + existing_files,
                    check=True,
                )

            file_size = backup_file.stat().st_size
            self.stdout.write(
                self.style.SUCCESS(f"Config backup created: {backup_file} ({file_size} bytes)")
            )

            if verify:
                self.verify_tar_backup(backup_file)

        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f"Config backup failed: {e}"))
            raise
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Config backup error: {e}"))
            raise

    def verify_tar_backup(self, backup_file):
        self.stdout.write("Verifying tar backup...")

        try:
            # Use tar -t to list files and verify integrity
            subprocess.run(["tar", "-tzf", str(backup_file)], check=True, capture_output=True)
            self.stdout.write(self.style.SUCCESS("Tar backup verification passed"))
        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f"Tar backup verification failed: {e}"))
            raise
