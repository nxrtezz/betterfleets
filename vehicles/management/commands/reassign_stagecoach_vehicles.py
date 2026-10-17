from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from busstops.models import Operator
from bustimes.models import Garage
from vehicles.models import Vehicle, VehicleJourney


class Command(BaseCommand):
    help = "Automatically reassign Stagecoach vehicles to garage-specific operators based on their tracking"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without making changes",
        )
        parser.add_argument(
            "--hours",
            type=int,
            default=24,
            help="Only check vehicles that have tracked in the last N hours (default: 24)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        hours = options["hours"]

        self.stdout.write(f"Checking Stagecoach vehicle reassignments (last {hours} hours)...")

        # Find all Stagecoach operators (those with "Stagecoach" in the name)
        stagecoach_operators = Operator.objects.filter(name__icontains="Stagecoach")

        if not stagecoach_operators.exists():
            self.stdout.write(self.style.WARNING("No Stagecoach operators found"))
            return

        self.stdout.write(f"Found {stagecoach_operators.count()} Stagecoach operators")

        # Get all vehicles that:
        # 1. Belong to a Stagecoach operator
        # 2. Have tracked in the last N hours
        since = timezone.now() - timedelta(hours=hours)
        vehicles = Vehicle.objects.filter(
            operator__in=stagecoach_operators,
            latest_journey__datetime__gte=since,
        ).select_related("operator", "latest_journey", "latest_journey__trip", "latest_journey__trip__garage")

        self.stdout.write(f"Found {vehicles.count()} vehicles to check")

        changes_made = 0

        for vehicle in vehicles:
            journey = vehicle.latest_journey
            if not journey:
                continue

            trip = journey.trip
            if not trip:
                continue

            garage = trip.garage
            if not garage:
                continue

            garage_name = garage.name.lower().strip()

            # Check if the garage name matches a Stagecoach operator
            # Look for operators like "Stagecoach Portsmouth", "Stagecoach London", etc.
            target_operator = stagecoach_operators.filter(
                name__icontains=garage_name
            ).first()

            if not target_operator:
                # Try matching with code as well
                target_operator = stagecoach_operators.filter(
                    name__icontains=garage.code.lower()
                ).first()

            if target_operator and target_operator != vehicle.operator:
                # Vehicle should be reassigned
                old_operator = vehicle.operator
                service_name = journey.route_name or journey.service_id or "unknown service"

                if dry_run:
                    self.stdout.write(
                        f"[DRY RUN] Would reassign {vehicle} from {old_operator} to {target_operator} "
                        f"(garage: {garage.name}, service: {service_name})"
                    )
                else:
                    vehicle.operator = target_operator
                    vehicle.save(update_fields=["operator"])
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Reassigned {vehicle} from {old_operator} to {target_operator} "
                            f"(garage: {garage.name}, service: {service_name})"
                        )
                    )
                    changes_made += 1

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run complete - no changes made"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Complete - {changes_made} vehicles reassigned"))
