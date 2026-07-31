from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from vehicles.models import Livery, Vehicle


class Command(BaseCommand):
    help = "Delete Bustimes-origin liveries only, preserving manual/local records"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--unused-only",
            action="store_true",
            help="Only delete Bustimes-origin liveries that are not referenced by any vehicles",
        )

    def handle(self, *args, **options):
        self.options = options

        if options["dry_run"]:
            with transaction.atomic():
                self._purge()
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Dry run: all DB writes rolled back"))
            return

        self._purge()

    def _target_queryset(self):
        queryset = Livery.objects.filter(external_id__isnull=False, is_manual=False)
        if self.options.get("unused_only"):
            queryset = queryset.annotate(vehicle_count=Count("vehicle")).filter(vehicle_count=0)
        return queryset

    def _purge(self):
        queryset = self._target_queryset()
        scanned = queryset.count()
        vehicle_refs = Vehicle.objects.filter(livery__in=queryset).count()
        deleted, deleted_details = queryset.delete()
        deleted_liveries = deleted_details.get("vehicles.Livery", 0)

        self.stdout.write(
            "Bustimes liveries: "
            f"scanned={scanned} "
            f"vehicle_refs_cleared={vehicle_refs} "
            f"deleted={deleted_liveries} "
            f"total_objects={deleted}"
        )
