from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from busstops.models import DataSource, Operator
from vehicles.models import Vehicle


class Command(BaseCommand):
    help = "Delete Bustimes-imported vehicles only, optionally limited to one operator"

    source_name = "Bustimes Fleet API"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--operator", help="Filter by operator noc or slug")

    def handle(self, *args, **options):
        self.options = options
        self.source = DataSource.objects.filter(name=self.source_name).first()
        self.operator = self._resolve_operator(options.get("operator"))

        if options["dry_run"]:
            with transaction.atomic():
                self._purge()
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Dry run: all DB writes rolled back"))
            return

        self._purge()

    def _resolve_operator(self, value):
        if not value:
            return None
        return Operator.objects.filter(Q(noc__iexact=value) | Q(slug__iexact=value)).first()

    def _target_queryset(self):
        if not self.source:
            return Vehicle.objects.none()

        queryset = Vehicle.objects.filter(source=self.source, is_manual=False)

        operator_filter = self.options.get("operator")
        if self.operator:
            queryset = queryset.filter(operator=self.operator)
        elif operator_filter:
            queryset = queryset.filter(
                Q(operator__noc__iexact=operator_filter)
                | Q(operator__slug__iexact=operator_filter)
            )

        return queryset

    def _purge(self):
        queryset = self._target_queryset()
        scanned = queryset.count()
        deleted, deleted_details = queryset.delete()
        deleted_vehicles = deleted_details.get("vehicles.Vehicle", 0)

        self.stdout.write(
            f"Bustimes vehicles: scanned={scanned} deleted={deleted_vehicles} total_objects={deleted}"
        )
