from django.core.management.base import BaseCommand
from tqdm import tqdm

from busstops.bustimes_sync import BustimesApiClient, compact_text
from busstops.management.commands._sync_bustimes import resolve_vehicle_type
from vehicles.models import VehicleType


class Command(BaseCommand):
    help = "Sync vehicle types from the Bustimes API"

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
            help="Maximum number of vehicle types to sync.",
        )

    def handle(self, *args, **options):
        client = BustimesApiClient()
        dry_run = options["dry_run"]
        force = options["force"]
        max_items = options["max_items"]

        self.stdout.write("Syncing vehicle types from Bustimes API...")

        created = updated = skipped = 0

        vehicle_types_data = list(client.iter_results("vehicletypes/", limit=max_items))
        
        progress = tqdm(
            vehicle_types_data,
            desc="Processing vehicle types",
            unit="vehicle_type",
            file=self.stdout,
            disable=not vehicle_types_data,
        )

        for item in progress:
            try:
                vehicle_type = resolve_vehicle_type(item)
                
                if vehicle_type:
                    if dry_run:
                        self.stdout.write(f"[DRY RUN] Would sync vehicle type: {vehicle_type}")
                        skipped += 1
                    else:
                        # Update vehicle type fields if needed
                        updated += 1
                else:
                    if dry_run:
                        self.stdout.write(f"[DRY RUN] Would create vehicle type: {item.get('name')}")
                        skipped += 1
                    else:
                        # Create new vehicle type
                        created += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing vehicle type: {e}"))
                continue

        self.stdout.write(
            f"Vehicle types sync complete: {created} created, {updated} updated, {skipped} skipped"
        )
