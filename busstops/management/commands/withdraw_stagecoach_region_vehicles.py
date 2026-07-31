from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from vehicles.models import Vehicle


DEFAULT_NOCS = (
    "SCCD",
    "SCCM",
    "SCCS",
    "SCBL",
    "SBLB",
    "NFKG",
    "LIBC",
    "IBTL",
    "EMSY",
    "ELBG",
    "CLTL",
    "BNSM",
)


class Command(BaseCommand):
    help = (
        "Withdraw Stagecoach vehicles that are still attached to region-style "
        "operators instead of Stagecoach garage operators. Dry-run by default; "
        "pass --apply to write changes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write withdrawn flags. Without this flag the command only reports matches.",
        )
        parser.add_argument(
            "--nocs",
            nargs="+",
            default=list(DEFAULT_NOCS),
            help="Operator NOCs to inspect.",
        )

    @staticmethod
    def normalise_garage_name(vehicle: Vehicle) -> str:
        return " ".join(str(vehicle.garage or "").strip().split())

    def handle(self, *args, apply=False, nocs=None, **options):
        self.stdout.write(
            self.style.WARNING("Dry run: no changes will be written.")
            if not apply
            else self.style.SUCCESS("Apply mode: withdrawing mismatched Stagecoach vehicles.")
        )

        vehicles = (
            Vehicle.objects.select_related("operator", "garage")
            .filter(operator__noc__in=nocs, operator__name__startswith="Stagecoach ")
            .order_by("operator__noc", "fleet_number", "fleet_code", "code")
        )

        matched = 0
        withdrawn = 0

        with transaction.atomic():
            for vehicle in vehicles:
                garage_name = self.normalise_garage_name(vehicle)
                expected_name = f"Stagecoach {garage_name}" if garage_name else None

                if expected_name and vehicle.operator.name == expected_name:
                    continue

                matched += 1
                self.stdout.write(
                    f"{vehicle.id}: {vehicle.operator.noc} {vehicle.operator.name} "
                    f"[garage={garage_name or '-'}] -> withdraw"
                )

                if apply and not vehicle.withdrawn:
                    vehicle.withdrawn = True
                    vehicle.save(update_fields=["withdrawn"])
                    withdrawn += 1

            if not apply:
                transaction.set_rollback(True)

        self.stdout.write(
            self.style.SUCCESS(
                f"Matched {matched} vehicle(s); withdrew {withdrawn} vehicle(s)."
            )
        )
