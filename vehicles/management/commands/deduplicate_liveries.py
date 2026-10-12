from django.core.management.base import BaseCommand
from django.db.models import Count

from vehicles.models import Livery, Vehicle


class Command(BaseCommand):
    help = "Deduplicate liveries with the same name by merging vehicles"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)

        # Find livery names that have duplicates
        duplicate_liveries = (
            Livery.objects.values("name")
            .annotate(count=Count("id"))
            .filter(count__gt=1)
            .order_by("-count")
        )

        if not duplicate_liveries:
            self.stdout.write("No duplicate liveries found")
            return

        self.stdout.write(f"Found {duplicate_liveries.count()} livery name(s) with duplicates")

        for item in duplicate_liveries:
            livery_name = item["name"]
            count = item["count"]
            
            # Get all liveries with this name
            liveries = list(Livery.objects.filter(name=livery_name).order_by("id"))
            
            if len(liveries) < 2:
                continue
            
            # Keep the first one (oldest), merge others into it
            primary_livery = liveries[0]
            duplicate_liveries = liveries[1:]
            
            self.stdout.write(f"\n{livery_name}: {count} liveries, keeping ID {primary_livery.id}")
            
            for duplicate in duplicate_liveries:
                vehicle_count = duplicate.vehicle_set.count()
                self.stdout.write(f"  - Merging ID {duplicate.id} ({vehicle_count} vehicles) into ID {primary_livery.id}")
                
                if not dry_run:
                    # Reassign vehicles to primary livery
                    duplicate.vehicle_set.update(livery=primary_livery)
                    # Delete duplicate livery
                    duplicate.delete()
            
            if not dry_run:
                self.stdout.write(f"  → Merged {len(duplicate_liveries)} duplicate(s)")
        
        if dry_run:
            self.stdout.write("\nDry run complete - no changes made")
        else:
            self.stdout.write("\nDeduplication complete")
