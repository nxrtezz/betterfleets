import contextlib

from django.core.management.base import BaseCommand
from django.db import IntegrityError
from django.db.models import Count

from vehicles.models import Vehicle, VehicleCode


class Command(BaseCommand):
    help = "Merge duplicate vehicles based on code and operator (for AVL tracking deduplication)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without making changes",
        )
        parser.add_argument(
            "--operator",
            type=str,
            help="Only process vehicles for a specific operator (by NOC code)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        operator_filter = options.get("operator")

        self.stdout.write("Finding duplicate vehicles...")

        # Get all vehicles that have a latest journey with VehicleRef data
        vehicles = Vehicle.objects.exclude(latest_journey_data=None)

        if operator_filter:
            vehicles = vehicles.filter(operator_id=operator_filter)

        total_merged = 0

        for vehicle in vehicles:
            if not vehicle.latest_journey_data:
                continue

            try:
                monitored_vehicle_journey = vehicle.latest_journey_data.get("MonitoredVehicleJourney", {})
                vehicle_ref = monitored_vehicle_journey.get("VehicleRef", "")
                operator_ref = monitored_vehicle_journey.get("OperatorRef", "")
            except (AttributeError, TypeError):
                continue

            if not vehicle_ref:
                continue

            # Remove operator prefix if present
            vehicle_ref = vehicle_ref.removeprefix(f"{operator_ref}-")

            # The expected slug format is {operator}-{code}
            expected_slug = f"{vehicle.operator_id.lower()}-{vehicle_ref.lower()}" if vehicle.operator_id else vehicle_ref.lower()

            # If the current vehicle's slug doesn't match the expected slug from VehicleRef
            if vehicle.slug.lower() != expected_slug:
                # Try to find a vehicle with the expected slug in the same operator
                try:
                    target_vehicle = Vehicle.objects.get(
                        slug__iexact=expected_slug,
                        operator_id=vehicle.operator_id,
                    )

                    if target_vehicle.id != vehicle.id:
                        # Found a match - merge this vehicle into the target
                        self.stdout.write(
                            f"\nFound mismatch: {vehicle.slug} (id={vehicle.id}) "
                            f"should be {expected_slug} (id={target_vehicle.id})"
                        )

                        if dry_run:
                            self.stdout.write(
                                f"[DRY RUN] Would merge {vehicle.slug} into {target_vehicle.slug}"
                            )
                            total_merged += 1
                        else:
                            self.merge_vehicle(vehicle, target_vehicle)
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"Merged {vehicle.slug} (id={vehicle.id}) into {target_vehicle.slug}"
                                )
                            )
                            total_merged += 1
                except Vehicle.DoesNotExist:
                    # No matching vehicle found - skip
                    pass
                except Vehicle.MultipleObjectsReturned:
                    # Multiple matches - skip to be safe
                    self.stdout.write(
                        self.style.WARNING(
                            f"Multiple vehicles found with slug {expected_slug}, skipping"
                        )
                    )

        # Also handle duplicates by reg
        from django.db.models import Count

        reg_duplicates = (
            Vehicle.objects.values("reg", "operator_id")
            .annotate(count=Count("id"))
            .filter(count__gt=1)
            .exclude(reg="")
        )

        if operator_filter:
            reg_duplicates = reg_duplicates.filter(operator_id=operator_filter)

        # Also handle duplicates by fleet code
        fleet_code_duplicates = (
            Vehicle.objects.values("fleet_code", "operator_id")
            .annotate(count=Count("id"))
            .filter(count__gt=1)
            .exclude(fleet_code="")
        )

        if operator_filter:
            fleet_code_duplicates = fleet_code_duplicates.filter(operator_id=operator_filter)

        for duplicate in reg_duplicates:
            reg = duplicate["reg"]
            operator_id = duplicate["operator_id"]

            # Get all vehicles with this reg and operator
            vehicles = Vehicle.objects.filter(
                reg__iexact=reg,
                operator_id=operator_id,
            ).order_by("id")

            if vehicles.count() < 2:
                continue

            # Keep the vehicle with the most data
            def score_vehicle(v):
                score = 0
                if v.livery_id:
                    score += 5
                if v.vehicle_type_id:
                    score += 3
                if v.colours:
                    score += 2
                if v.branding:
                    score += 2
                if v.name:
                    score += 1
                # Prefer older vehicles if scores are equal
                score -= v.id / 1000000
                return score

            vehicles_list = list(vehicles)
            vehicle_to_keep = max(vehicles_list, key=score_vehicle)
            vehicles_to_merge = [v for v in vehicles_list if v != vehicle_to_keep]

            self.stdout.write(
                f"\nFound {vehicles.count()} vehicles with reg '{reg}' "
                f"and operator {operator_id}:"
            )
            for v in vehicles:
                self.stdout.write(f"  - {v.slug} (id={v.id}, code={v.code})")

            for duplicate_vehicle in vehicles_to_merge:
                if dry_run:
                    self.stdout.write(
                        f"[DRY RUN] Would merge {duplicate_vehicle.slug} into {vehicle_to_keep.slug}"
                    )
                    total_merged += 1
                else:
                    self.merge_vehicle(duplicate_vehicle, vehicle_to_keep)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Merged {duplicate_vehicle.slug} (id={duplicate_vehicle.id}) into {vehicle_to_keep.slug}"
                        )
                    )
                    total_merged += 1

        # Process fleet code duplicates
        for duplicate in fleet_code_duplicates:
            fleet_code = duplicate["fleet_code"]
            operator_id = duplicate["operator_id"]

            # Get all vehicles with this fleet code and operator
            vehicles = Vehicle.objects.filter(
                fleet_code__iexact=fleet_code,
                operator_id=operator_id,
            ).order_by("id")

            if vehicles.count() < 2:
                continue

            # Keep the vehicle with the most data
            def score_vehicle(v):
                score = 0
                if v.livery_id:
                    score += 5
                if v.vehicle_type_id:
                    score += 3
                if v.colours:
                    score += 2
                if v.branding:
                    score += 2
                if v.name:
                    score += 1
                if v.reg:
                    score += 1
                # Prefer older vehicles if scores are equal
                score -= v.id / 1000000
                return score

            vehicles_list = list(vehicles)
            vehicle_to_keep = max(vehicles_list, key=score_vehicle)
            vehicles_to_merge = [v for v in vehicles_list if v != vehicle_to_keep]

            self.stdout.write(
                f"\nFound {vehicles.count()} vehicles with fleet code '{fleet_code}' "
                f"and operator {operator_id}:"
            )
            for v in vehicles:
                self.stdout.write(f"  - {v.slug} (id={v.id}, reg={v.reg})")

            for duplicate_vehicle in vehicles_to_merge:
                if dry_run:
                    self.stdout.write(
                        f"[DRY RUN] Would merge {duplicate_vehicle.slug} into {vehicle_to_keep.slug}"
                    )
                    total_merged += 1
                else:
                    self.merge_vehicle(duplicate_vehicle, vehicle_to_keep)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Merged {duplicate_vehicle.slug} (id={duplicate_vehicle.id}) into {vehicle_to_keep.slug}"
                        )
                    )
                    total_merged += 1

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"\nDry run complete - would merge {total_merged} vehicles")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"\nComplete - merged {total_merged} vehicles")
            )

    def merge_vehicle(self, vehicle_to_delete, vehicle_to_keep):
        """Merge one vehicle into another"""
        # Move related objects
        vehicle_to_delete.vehiclejourney_set.update(vehicle=vehicle_to_keep)
        vehicle_to_delete.vehiclecode_set.update(vehicle=vehicle_to_keep)
        vehicle_to_delete.vehiclerevision_set.update(vehicle=vehicle_to_keep)

        # Ensure the slug is preserved as a vehicle code
        with contextlib.suppress(IntegrityError):
            VehicleCode.objects.create(
                vehicle=vehicle_to_keep, scheme="slug", code=vehicle_to_keep.slug
            )

        # Copy fields from duplicate if they're better
        if not vehicle_to_keep.slug or vehicle_to_delete.slug:
            vehicle_to_keep.slug = vehicle_to_delete.slug
        if not vehicle_to_keep.code or vehicle_to_delete.code:
            vehicle_to_keep.code = vehicle_to_delete.code

        # Keep the most recent journey
        if not vehicle_to_keep.latest_journey_id or (
            vehicle_to_delete.latest_journey_id
            and vehicle_to_delete.latest_journey_id > vehicle_to_keep.latest_journey_id
        ):
            vehicle_to_keep.latest_journey = vehicle_to_delete.latest_journey

        # If the kept vehicle is withdrawn but the duplicate isn't, restore it
        if vehicle_to_keep.withdrawn and not vehicle_to_delete.withdrawn:
            vehicle_to_keep.fleet_code = vehicle_to_delete.fleet_code
            vehicle_to_keep.fleet_number = vehicle_to_delete.fleet_number
            vehicle_to_keep.withdrawn = False

        # Copy other fields if the kept vehicle doesn't have them
        if not vehicle_to_keep.reg and vehicle_to_delete.reg:
            vehicle_to_keep.reg = vehicle_to_delete.reg
        if not vehicle_to_keep.livery_id and vehicle_to_delete.livery_id:
            vehicle_to_keep.livery = vehicle_to_delete.livery
        if not vehicle_to_keep.vehicle_type_id and vehicle_to_delete.vehicle_type_id:
            vehicle_to_keep.vehicle_type = vehicle_to_delete.vehicle_type
        if not vehicle_to_keep.colours and vehicle_to_delete.colours:
            vehicle_to_keep.colours = vehicle_to_delete.colours
        if not vehicle_to_keep.branding and vehicle_to_delete.branding:
            vehicle_to_keep.branding = vehicle_to_delete.branding

        # Delete the duplicate
        duplicate_slug = vehicle_to_delete.slug
        vehicle_to_delete.delete()

        # Save the kept vehicle with all updates
        vehicle_to_keep.save(
            update_fields=[
                "slug",
                "code",
                "reg",
                "fleet_code",
                "fleet_number",
                "withdrawn",
                "latest_journey",
                "livery",
                "vehicle_type",
                "colours",
                "branding",
            ]
        )
