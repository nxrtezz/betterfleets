from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from vehicles.models import Vehicle


class Command(BaseCommand):
    help = "Audit vehicles with missing liveries, optionally filtered to one operator"

    def add_arguments(self, parser):
        parser.add_argument("--operator", help="Filter by operator noc or slug")
        parser.add_argument("--limit", type=int, default=50, help="Maximum unresolved vehicles to print")

    def handle(self, *args, **options):
        queryset = Vehicle.objects.filter(livery__isnull=True, withdrawn=False).select_related(
            "operator", "vehicle_type", "garage"
        )

        operator_filter = options.get("operator")
        if operator_filter:
            queryset = queryset.filter(
                Q(operator__noc__iexact=operator_filter)
                | Q(operator__slug__iexact=operator_filter)
            )

        total = queryset.count()
        self.stdout.write(f"missing_liveries={total}")

        by_operator = (
            queryset.values("operator__noc", "operator__name")
            .annotate(vehicle_count=Count("id"))
            .order_by("-vehicle_count", "operator__name")
        )
        for row in by_operator[:25]:
            noc = row["operator__noc"] or "-"
            name = row["operator__name"] or "Unassigned"
            self.stdout.write(f"operator={noc} name={name} missing={row['vehicle_count']}")

        self.stdout.write("sample_unresolved:")
        for vehicle in queryset.order_by("operator__name", "fleet_number", "fleet_code", "reg", "code")[: options["limit"]]:
            self.stdout.write(
                "  "
                f"id={vehicle.pk} "
                f"operator={getattr(vehicle.operator, 'noc', '-') } "
                f"code={vehicle.code or '-'} "
                f"reg={vehicle.reg or '-'} "
                f"type={getattr(vehicle.vehicle_type, 'name', '-') } "
                f"garage={getattr(vehicle.garage, 'code', '-') }"
            )
