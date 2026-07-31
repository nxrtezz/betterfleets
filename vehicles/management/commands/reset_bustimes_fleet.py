from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from busstops.models import DataSource, Operator
from vehicles.models import Vehicle


class Command(BaseCommand):
    help = (
        "Delete Bustimes-imported vehicles, reimport them from the Bustimes fleet API, "
        "and repair any missing liveries afterwards"
    )

    source_name = "Bustimes Fleet API"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--operator", help="Filter by operator noc or slug")
        parser.add_argument("--livery", help="Filter reimported vehicles by Bustimes livery id/external_id")
        parser.add_argument("--skip-operators", action="store_true")
        parser.add_argument("--since", help="Incremental watermark where supported by API")
        parser.add_argument("--limit", type=int, help="Maximum items per endpoint request")

    def handle(self, *args, **options):
        self.options = options
        self.operator = self._resolve_operator(options.get("operator"))
        self.source = DataSource.objects.filter(name=self.source_name).first()

        if options["dry_run"]:
            with transaction.atomic():
                self._run_reset_cycle()
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Dry run: all DB writes rolled back"))
            return

        self._run_reset_cycle()

    def _run_reset_cycle(self):
        target_queryset = self._target_queryset()
        scanned = target_queryset.count()
        deleted, deleted_details = target_queryset.delete()
        deleted_vehicles = deleted_details.get("vehicles.Vehicle", 0)

        self.stdout.write(
            f"Bustimes vehicles: scanned={scanned} deleted={deleted_vehicles}"
        )

        sync_options = {
            "dry_run": self.options["dry_run"],
            "skip_operators": self.options.get("skip_operators", False),
            "since": self.options.get("since"),
            "limit": self.options.get("limit"),
            "stdout": self.stdout,
            "stderr": self.stderr,
        }
        if self.options.get("operator"):
            sync_options["operator"] = self.options["operator"]
        if self.options.get("livery"):
            sync_options["livery"] = self.options["livery"]

        repair_options = {
            "dry_run": self.options["dry_run"],
            "since": self.options.get("since"),
            "limit": self.options.get("limit"),
            "stdout": self.stdout,
            "stderr": self.stderr,
        }
        if self.options.get("operator"):
            repair_options["operator"] = self.options["operator"]

        call_command("sync_bustimes_fleet", **sync_options)
        call_command("repair_vehicle_liveries", **repair_options)

    def _resolve_operator(self, value):
        if not value:
            return None
        return Operator.objects.filter(Q(pk__iexact=value) | Q(slug__iexact=value)).first()

    def _target_queryset(self):
        queryset = Vehicle.objects.filter(is_manual=False)
        if self.source:
            queryset = queryset.filter(source=self.source)
        else:
            queryset = queryset.none()

        if self.operator:
            queryset = queryset.filter(operator=self.operator)
        elif self.options.get("operator"):
            queryset = queryset.filter(
                Q(operator_id__iexact=self.options["operator"])
                | Q(operator__slug__iexact=self.options["operator"])
            )

        return queryset
