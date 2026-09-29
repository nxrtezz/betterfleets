"""
Comprehensive timetable refresh command.

This command runs all timetable refresh operations:
1. Refresh all TransXChange sources
2. Refresh TNDS data (if credentials provided)
3. Import/update BODS timetables (if API key provided)
4. Sync stops from Bustimes API

Uses environment variables for credentials:
- TNDS_USERNAME, TNDS_PASSWORD for TNDS FTP access
- BODS_API_KEY for Bus Open Data Service API access
"""

import os
import time
import logging
from django.core.management import call_command, BaseCommand
from django.core.management.base import CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Refresh all timetable data sources using environment variables for credentials"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-transxchange",
            action="store_true",
            help="Skip TransXChange sources refresh.",
        )
        parser.add_argument(
            "--skip-tnds",
            action="store_true",
            help="Skip TNDS data refresh.",
        )
        parser.add_argument(
            "--skip-bods",
            action="store_true",
            help="Skip BODS timetables import.",
        )
        parser.add_argument(
            "--skip-stops",
            action="store_true",
            help="Skip Bustimes stops sync.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Perform a dry run without making changes (where supported).",
        )
        parser.add_argument(
            "--max-retries",
            type=int,
            default=3,
            help="Maximum number of retries for failed steps (default: 3).",
        )

    def retry_with_backoff(self, func, step_name, max_retries=3):
        """
        Execute a function with exponential backoff retry logic.
        Backoff sequence: 2s, 4s, 8s
        """
        retry_count = 0
        backoff_times = [2, 4, 8]
        
        while retry_count < max_retries:
            try:
                self.stdout.write(f"\n{'='*70}")
                self.stdout.write(f"🔄 Executing: {step_name}")
                self.stdout.write(f"{'='*70}")
                
                func()
                self.stdout.write(self.style.SUCCESS(f"✓ {step_name} completed successfully"))
                return True
                
            except Exception as exc:
                retry_count += 1
                error_msg = str(exc).lower()
                
                # Check if error is retryable
                is_retryable = (
                    "timeout" in error_msg or
                    "rate limit" in error_msg or
                    "connection" in error_msg or
                    "network" in error_msg or
                    "503" in error_msg or
                    "502" in error_msg or
                    "429" in error_msg
                )
                
                if retry_count < max_retries and is_retryable:
                    backoff_time = backoff_times[min(retry_count - 1, len(backoff_times) - 1)]
                    self.stdout.write(
                        self.style.WARNING(
                            f"⚠️  {step_name} failed (attempt {retry_count}/{max_retries}): {exc}"
                        )
                    )
                    self.stdout.write(f"⏳ Retrying in {backoff_time}s...")
                    time.sleep(backoff_time)
                else:
                    self.stdout.write(
                        self.style.ERROR(
                            f"✗ {step_name} failed: {exc}"
                        )
                    )
                    return False
        
        return False

    def refresh_transxchange_sources(self):
        """Refresh all TransXChange sources"""
        def refresh():
            call_command("refresh_transxchange_sources", "--all")
        
        if not self.retry_with_backoff(refresh, "TransXChange Sources Refresh", self.max_retries):
            raise CommandError("TransXChange sources refresh failed")

    def refresh_tnds_data(self):
        """Refresh TNDS data using environment variables"""
        username = os.environ.get("TNDS_USERNAME")
        password = os.environ.get("TNDS_PASSWORD")
        
        if not username or not password:
            self.stdout.write(
                self.style.WARNING(
                    "⚠️  TNDS_USERNAME or TNDS_PASSWORD not set, skipping TNDS refresh"
                )
            )
            return
        
        def refresh():
            call_command("refresh_tnds_data", username, password)
        
        if not self.retry_with_backoff(refresh, "TNDS Data Refresh", self.max_retries):
            self.stdout.write(self.style.WARNING("⚠️  TNDS refresh failed, continuing..."))

    def import_bods_timetables(self):
        """Import BODS timetables using environment variable"""
        api_key = os.environ.get("BODS_API_KEY")
        
        if not api_key:
            self.stdout.write(
                self.style.WARNING(
                    "⚠️  BODS_API_KEY not set, skipping BODS import"
                )
            )
            return
        
        def import_bods():
            if self.dry_run:
                call_command("import_timetable_data", "bod", api_key, "--dry-run")
            else:
                call_command("import_timetable_data", "bod", api_key)
        
        if not self.retry_with_backoff(import_bods, "BODS Timetables Import", self.max_retries):
            self.stdout.write(self.style.WARNING("⚠️  BODS import failed, continuing..."))

    def sync_bustimes_stops(self):
        """Sync stops from Bustimes API"""
        def sync():
            if self.dry_run:
                call_command("sync_bustimes_stops", "--dry-run")
            else:
                call_command("sync_bustimes_stops")
        
        if not self.retry_with_backoff(sync, "Bustimes Stops Sync", self.max_retries):
            raise CommandError("Bustimes stops sync failed")

    def handle(self, *args, **options):
        self.stdout.write("\n" + "="*70)
        self.stdout.write("🚀 COMPREHENSIVE TIMETABLE REFRESH")
        self.stdout.write("="*70)
        self.stdout.write("This command will refresh all timetable data sources.")
        self.stdout.write("="*70)
        
        self.skip_transxchange = options["skip_transxchange"]
        self.skip_tnds = options["skip_tnds"]
        self.skip_bods = options["skip_bods"]
        self.skip_stops = options["skip_stops"]
        self.dry_run = options["dry_run"]
        self.max_retries = options["max_retries"]
        
        if self.dry_run:
            self.stdout.write(self.style.WARNING("⚠️  DRY RUN MODE - Changes may be limited"))
        
        start_time = time.time()
        failed_steps = []
        
        try:
            # Step 1: TransXChange sources
            if not self.skip_transxchange:
                try:
                    self.refresh_transxchange_sources()
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"✗ TransXChange refresh failed: {e}"))
                    failed_steps.append("TransXChange sources")
            
            # Step 2: TNDS data
            if not self.skip_tnds:
                try:
                    self.refresh_tnds_data()
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"✗ TNDS refresh failed: {e}"))
                    failed_steps.append("TNDS data")
            
            # Step 3: BODS timetables
            if not self.skip_bods:
                try:
                    self.import_bods_timetables()
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"✗ BODS import failed: {e}"))
                    failed_steps.append("BODS timetables")
            
            # Step 4: Bustimes stops
            if not self.skip_stops:
                try:
                    self.sync_bustimes_stops()
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"✗ Bustimes stops sync failed: {e}"))
                    failed_steps.append("Bustimes stops")
            
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\n⚠️  Refresh interrupted by user"))
            raise
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n✗ Fatal error: {e}"))
            raise
        
        # Summary
        elapsed_time = time.time() - start_time
        hours = int(elapsed_time // 3600)
        minutes = int((elapsed_time % 3600) // 60)
        seconds = int(elapsed_time % 60)
        
        self.stdout.write("\n" + "="*70)
        self.stdout.write("📊 REFRESH SUMMARY")
        self.stdout.write("="*70)
        self.stdout.write(f"Total time: {hours}h {minutes}m {seconds}s")
        
        if failed_steps:
            self.stdout.write(self.style.WARNING(f"⚠️  Failed steps: {', '.join(failed_steps)}"))
        else:
            self.stdout.write(self.style.SUCCESS("✓ All steps completed successfully"))
        
        self.stdout.write("="*70)