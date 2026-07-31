import os
import subprocess
import gzip
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Restore from backup (database, media, or configuration)"

    def add_arguments(self, parser):
        parser.add_argument(
            "backup_file",
            help="Path to backup file to restore",
        )
        parser.add_argument(
            "--type",
            choices=["database", "media", "config"],
            required=True,
            help="Type of backup to restore",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Skip confirmation prompt",
        )

    def handle(self, *args, **options):
        backup_file = Path(options["backup_file"])
        backup_type = options["type"]
        force = options["force"]

        if not backup_file.exists():
            self.stdout.write(self.style.ERROR(f"Backup file not found: {backup_file}"))
            return

        if not force:
            self.stdout.write(f"WARNING: This will restore {backup_type} from {backup_file}")
            self.stdout.write("This operation cannot be undone.")
            confirm = input("Are you sure you want to continue? (yes/no): ")
            if confirm.lower() != "yes":
                self.stdout.write("Restore cancelled")
                return

        self.stdout.write(f"Restoring {backup_type} from {backup_file}...")

        if backup_type == "database":
            self.restore_database(backup_file)
        elif backup_type == "media":
            self.restore_media(backup_file)
        elif backup_type == "config":
            self.restore_config(backup_file)

        self.stdout.write(self.style.SUCCESS("Restore completed successfully"))

    def restore_database(self, backup_file):
        self.stdout.write("Restoring PostgreSQL database...")

        # Get database connection details
        db_config = settings.DATABASES["default"]
        db_name = db_config["NAME"]
        db_user = db_config["USER"]
        db_host = db_config["HOST"]
        db_port = db_config["PORT"]
        db_password = db_config["PASSWORD"]

        try:
            # Build psql command
            psql_cmd = [
                "psql",
                f"--dbname=postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}",
            ]

            if backup_file.suffix == ".gz":
                # Decompress and restore
                with gzip.open(backup_file, "rb") as f:
                    process = subprocess.Popen(
                        psql_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                    process.communicate(input=f.read())
                    if process.returncode != 0:
                        raise subprocess.CalledProcessError(
                            process.returncode, psql_cmd, process.stderr
                        )
            else:
                with open(backup_file, "r") as f:
                    process = subprocess.Popen(
                        psql_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                    process.communicate(input=f.read())
                    if process.returncode != 0:
                        raise subprocess.CalledProcessError(
                            process.returncode, psql_cmd, process.stderr
                        )

            self.stdout.write(self.style.SUCCESS("Database restore completed"))

        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f"Database restore failed: {e}"))
            raise
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Database restore error: {e}"))
            raise

    def restore_media(self, backup_file):
        self.stdout.write("Restoring media files...")

        media_root = Path(getattr(settings, "MEDIA_ROOT", "./media"))

        try:
            # Remove existing media directory
            if media_root.exists():
                shutil.rmtree(media_root)

            # Restore from backup
            if backup_file.suffix == ".gz":
                subprocess.run(["tar", "-xzf", str(backup_file), "-C", str(media_root.parent)], check=True)
            else:
                subprocess.run(["tar", "-xf", str(backup_file), "-C", str(media_root.parent)], check=True)

            self.stdout.write(self.style.SUCCESS("Media restore completed"))

        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f"Media restore failed: {e}"))
            raise
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Media restore error: {e}"))
            raise

    def restore_config(self, backup_file):
        self.stdout.write("Restoring configuration files...")

        base_dir = Path(settings.BASE_DIR)

        try:
            # Restore from backup
            if backup_file.suffix == ".gz":
                subprocess.run(["tar", "-xzf", str(backup_file), "-C", str(base_dir)], check=True)
            else:
                subprocess.run(["tar", "-xf", str(backup_file), "-C", str(base_dir)], check=True)

            self.stdout.write(self.style.SUCCESS("Config restore completed"))
            self.stdout.write(self.style.WARNING("Please restart the application for configuration changes to take effect"))

        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f"Config restore failed: {e}"))
            raise
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Config restore error: {e}"))
            raise
