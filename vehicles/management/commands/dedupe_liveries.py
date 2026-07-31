from collections import defaultdict
from unittest.mock import patch

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import transaction

from vehicles.models import Livery, Vehicle, VehicleRevision


def canonical_css(css):
    return Livery.minify((css or "").strip())


class Command(BaseCommand):
    help = "Merge duplicate liveries that have the same name and same canonical CSS."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be merged without saving changes.",
        )
        parser.add_argument(
            "--name",
            help="Only deduplicate liveries with this exact name.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        name = options.get("name")

        liveries = Livery.objects.all().order_by("name", "id")
        if name:
            liveries = liveries.filter(name=name)

        groups = defaultdict(list)
        for livery in liveries:
            groups[(livery.name, canonical_css(livery.left_css))].append(livery)

        duplicate_groups = [items for items in groups.values() if len(items) > 1]

        stats = {
            "groups": len(duplicate_groups),
            "liveries_deleted": 0,
            "vehicles_reassigned": 0,
            "from_revisions_reassigned": 0,
            "to_revisions_reassigned": 0,
        }

        with patch.object(cache, "set", lambda *args, **kwargs: None), patch.object(cache, "delete", lambda *args, **kwargs: None), transaction.atomic():
            for items in duplicate_groups:
                keeper = self.choose_keeper(items)
                duplicates = [livery for livery in items if livery.id != keeper.id]
                duplicate_ids = [livery.id for livery in duplicates]

                vehicle_count = Vehicle.objects.filter(livery_id__in=duplicate_ids).count()
                from_revision_count = VehicleRevision.objects.filter(from_livery_id__in=duplicate_ids).count()
                to_revision_count = VehicleRevision.objects.filter(to_livery_id__in=duplicate_ids).count()

                stats["liveries_deleted"] += len(duplicates)
                stats["vehicles_reassigned"] += vehicle_count
                stats["from_revisions_reassigned"] += from_revision_count
                stats["to_revisions_reassigned"] += to_revision_count

                self.stdout.write(
                    f"{keeper.name}: keep {keeper.id}, merge {duplicate_ids} "
                    f"({vehicle_count} vehicles)"
                )

                if dry_run:
                    continue

                Vehicle.objects.filter(livery_id__in=duplicate_ids).update(livery=keeper)
                VehicleRevision.objects.filter(from_livery_id__in=duplicate_ids).update(from_livery=keeper)
                VehicleRevision.objects.filter(to_livery_id__in=duplicate_ids).update(to_livery=keeper)
                Livery.objects.filter(id__in=duplicate_ids).delete()

            if dry_run:
                transaction.set_rollback(True)

        prefix = "Dry run: " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                prefix + ", ".join(f"{key}={value}" for key, value in stats.items())
            )
        )

    def choose_keeper(self, liveries):
        vehicle_counts = {
            item.id: Vehicle.objects.filter(livery=item).count()
            for item in liveries
        }
        return sorted(
            liveries,
            key=lambda item: (-vehicle_counts[item.id], item.id),
        )[0]
