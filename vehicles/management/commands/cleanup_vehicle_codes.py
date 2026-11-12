"""
Remove VehicleCodes that belong to a different operator.

Feed identities sometimes end up attached to the wrong vehicle (e.g. a
TfL identity on a bus now operated by another company), which causes
mistracks when that operator's feed reports the identity. A code is
considered mismatched when the operator prefix embedded in it
(BODS 'NOC:...', slug 'noc-...', 'My Tracking' 'NOC:...') matches a
*different* known operator NOC than the vehicle's current operator.

Codes without an embedded operator prefix (TOPS numbers, TfE, jersey,
RTCSNV etc.) are left alone.
"""

import re

from django.core.management.base import BaseCommand
from django.db.models import Count

from busstops.models import Operator
from vehicles.models import VehicleCode

PREFIX_RE = re.compile(r"^([A-Za-z]+)[\-:]")


class Command(BaseCommand):
    help = "Delete vehicle codes belonging to a different operator"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="report mismatches without deleting",
        )

    def handle(self, *args, **options):
        nocs = set(Operator.objects.values_list("noc", flat=True))
        dry_run = options["dry_run"]

        mismatched = []
        for code in (
            VehicleCode.objects.select_related("vehicle")
            .only("id", "code", "scheme", "vehicle_id", "vehicle__operator_id")
            .iterator()
        ):
            operator_noc = code.vehicle.operator_id
            match = PREFIX_RE.match(code.code)
            if not match:
                continue
            prefix = match.group(1).upper()
            if prefix in nocs and prefix != operator_noc:
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
