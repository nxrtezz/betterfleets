from django.core.management.base import BaseCommand
from tqdm import tqdm

from busstops.bustimes_sync import BustimesApiClient, compact_text
from busstops.models import Operator


class Command(BaseCommand):
    help = "Sync operators from the Bustimes API"

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
            help="Maximum number of operators to sync.",
        )

    def handle(self, *args, **options):
        client = BustimesApiClient()
        dry_run = options["dry_run"]
        force = options["force"]
        max_items = options["max_items"]

        self.stdout.write("Syncing operators from Bustimes API...")

        created = updated = skipped = 0

        operators_data = list(client.iter_results("operators/", limit=max_items))
        
        self.stdout.write(f"Fetched {len(operators_data)} operators from API")
        
        if not operators_data:
            self.stdout.write(self.style.WARNING("No operators returned from API"))
            return
        
        progress = tqdm(
            operators_data,
            desc="Processing operators",
            unit="operator",
            file=self.stdout,
            disable=not operators_data,
        )

        for item in progress:
            try:
                noc = compact_text(item.get("noc") or item.get("id") or item.get("code"))
                name = compact_text(item.get("name"))
                external_id = compact_text(item.get("id")) or None
                
                if not noc:
                    self.stdout.write(f"Skipping item with no noc: {item}")
                    skipped += 1
                    continue
                
                # Try to find existing operator by noc (exact match first)
                operator = Operator.objects.filter(noc=noc).first()
                
                if not operator:
                    # Try case-insensitive match
                    operator = Operator.objects.filter(noc__iexact=noc).first()
                
                if operator:
                    if dry_run:
                        self.stdout.write(f"[DRY RUN] Would update operator: {operator.noc} - {operator.name}")
                        skipped += 1
                    else:
                        # Update operator fields if needed
                        if name and operator.name != name:
                            operator.name = name
                        if external_id and operator.external_id != external_id:
                            operator.external_id = external_id
                        operator.save()
                        updated += 1
                else:
                    if dry_run:
                        self.stdout.write(f"[DRY RUN] Would create operator: {noc} - {name}")
                        skipped += 1
                    else:
                        # Create new operator
                        self.stdout.write(f"Creating operator: {noc} - {name}")
                        operator = Operator.objects.create(
                            noc=noc,
                            name=name or noc,
                            external_id=external_id,
                        )
                        created += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing operator: {e}"))
                continue

        self.stdout.write(
            f"Operators sync complete: {created} created, {updated} updated, {skipped} skipped"
        )
