import time
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Sync all operators and vehicles from the Bustimes API, creating liveries and vehicle types from the vehicle data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Perform a dry run without making changes.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force updates even if fields are protected.",
        )
        parser.add_argument(
            "--max-items",
            type=int,
            help="Maximum number of items to sync per endpoint.",
        )
        parser.add_argument(
            "--max-retries",
            type=int,
            default=3,
            help="Maximum number of retries for failed requests (default: 3).",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=120,
            help="Timeout in seconds for API requests (default: 120).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]
        max_items = options["max_items"]
        max_retries = options["max_retries"]
        timeout = options["timeout"]

        self.stdout.write("\n" + "="*70)
        self.stdout.write("🚌 BUSTIMES API FULL SYNC")
        self.stdout.write("="*70)
        self.stdout.write("Syncing operators and vehicles from Bustimes API...")
        self.stdout.write("Liveries and vehicle types will be created from vehicle data")
        self.stdout.write("="*70)

        # Sync operators first
        self.stdout.write("\n" + "="*70)
        self.stdout.write("🔄 Syncing OPERATORS...")
        self.stdout.write("="*70)
        
        call_command(
            "sync_bustimes_operators",
            dry_run=dry_run,
            force=force,
            max_items=max_items,
        )

        # Sync vehicles (which will create liveries and vehicle types) with retry logic
        self.stdout.write("\n" + "="*70)
        self.stdout.write("🔄 Syncing VEHICLES...")
        self.stdout.write("="*70)
        
        retry_count = 0
        while retry_count < max_retries:
            try:
                call_command(
                    "sync_bustimes_vehicles",
                    dry_run=dry_run,
                    force=force,
                    max_items=max_items,
                    timeout=timeout,  # Use longer timeout for vehicles
                    override=True,  # Create new liveries if CSS doesn't match
                )
                break
            except Exception as exc:
                retry_count += 1
                if retry_count < max_retries and "timeout" in str(exc).lower():
                    # Exponential backoff: 10s, 20s, 40s
                    backoff_time = 10 * (2 ** (retry_count - 1))
                    self.stdout.write(f"⚠️  Vehicles sync timed out, retrying ({retry_count}/{max_retries}) in {backoff_time}s...")
                    time.sleep(backoff_time)
                else:
                    self.stdout.write(self.style.ERROR(f"✗ Vehicles sync failed: {exc}"))
                    if retry_count < max_retries:
                        self.stdout.write(f"⚠️  Retrying ({retry_count}/{max_retries})...")
                        time.sleep(5)
                    else:
                        self.stdout.write(self.style.ERROR("✗ Max retries reached, giving up"))
                        break

        self.stdout.write("\n" + "="*70)
        self.stdout.write("✓ FULL SYNC COMPLETED")
        self.stdout.write("="*70)
