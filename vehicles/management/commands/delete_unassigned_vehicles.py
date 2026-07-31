from django.core.management.base import BaseCommand
from django.db import transaction

from vehicles.models import Vehicle


class Command(BaseCommand):
    help = "Delete non-preserved vehicles that have no operator."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm-delete",
            action="store_true",
            help="Actually delete matching vehicles. Without this, the command only reports.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Only delete/report this many matching vehicles.",
        )

    def handle(self, *args, **options):
        confirm_delete = options["confirm_delete"]
        limit = options.get("limit")

        vehicles = Vehicle.objects.filter(operator__isnull=True, preserved=False).order_by("id")
        if limit is not None:
            vehicles = vehicles[:limit]

        vehicle_ids = list(vehicles.values_list("id", flat=True))
        count = len(vehicle_ids)
        preserved_count = Vehicle.objects.filter(operator__isnull=True, preserved=True).count()

        self.stdout.write(f"Matching non-preserved vehicles without operators: {count}")
        self.stdout.write(f"Preserved vehicles without operators left untouched: {preserved_count}")

        preview = list(
            Vehicle.objects.filter(id__in=vehicle_ids)
            .order_by("id")
            .values_list("id", "code", "fleet_code", "reg")[:25]
        )
        for vehicle_id, code, fleet_code, reg in preview:
            self.stdout.write(
                f"delete {vehicle_id}: code={code!r}, fleet_code={fleet_code!r}, reg={reg!r}"
            )
        if count > len(preview):
            self.stdout.write(f"...and {count - len(preview)} more")

        if not confirm_delete:
            self.stdout.write(
                self.style.WARNING("Dry run only. Re-run with --confirm-delete to delete them.")
            )
            return

        with transaction.atomic():
            deleted_count, deleted_by_model = Vehicle.objects.filter(id__in=vehicle_ids).delete()

        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_count} objects."))
        for model_name, model_count in sorted(deleted_by_model.items()):
            self.stdout.write(f"{model_name}: {model_count}")
