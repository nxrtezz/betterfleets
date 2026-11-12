"""
Remove VehicleCodes that belong to a different operator.

Feed identities sometimes end up attached to the wrong vehicle (e.g. a
TfL identity on a bus now operated by another company), which causes
mistracks when that operator's feed reports the identity. Uses
vehicles.models.vehicle_code_matches_operator - the same check the
live importers apply before creating codes.
"""

from django.core.management.base import BaseCommand

from busstops.models import Operator
from vehicles.models import VehicleCode, vehicle_code_matches_operator


class Command(BaseCommand):
    help = "Delete vehicle codes belonging to a different operator"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="report mismatches without deleting",
        )

    def handle(self, *args, **options):
        known_nocs = set(Operator.objects.values_list("noc", flat=True))
        dry_run = options["dry_run"]

        mismatched = []
        for code in (
            VehicleCode.objects.select_related("vehicle")
            .only("id", "code", "scheme", "vehicle_id", "vehicle__operator_id")
            .iterator()
        ):
            if not vehicle_code_matches_operator(
                code.code, code.vehicle.operator_id, known_nocs
            ):
                mismatched.append(code)

        by_scheme = {}
        for code in mismatched:
            by_scheme[code.scheme] = by_scheme.get(code.scheme, 0) + 1
        self.stdout.write(f"{len(mismatched)} mismatched codes")
        for scheme, count in sorted(by_scheme.items(), key=lambda x: -x[1]):
            self.stdout.write(f"  {scheme}: {count}")

        if dry_run:
            for code in mismatched[:50]:
                self.stdout.write(
                    f"  would delete {code.scheme} {code.code} "
                    f"(vehicle {code.vehicle_id}, operator {code.vehicle.operator_id})"
                )
            return

        deleted = VehicleCode.objects.filter(
            id__in=[code.id for code in mismatched]
        ).delete()
        self.stdout.write(f"deleted {deleted[0]} codes")
