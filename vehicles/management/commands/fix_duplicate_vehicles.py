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

        # Find all (code, operator) pairs that have multiple vehicles
        duplicate_pairs = (
            Vehicle.objects.values("code", "operator_id")
            .annotate(count=Count("id"))
            .filter(count__gt=1)
            .exclude(code="")
        )

        if operator_filter:
            duplicate_pairs = duplicate_pairs.filter(operator_id=operator_filter)

        total_merged = 0

        for duplicate in duplicate_pairs:
            code = duplicate["code"]
            operator_id = duplicate["operator_id"]

            if not code:
                continue

            # Get all vehicles with this code and operator, ordered by ID (oldest first)
            vehicles = Vehicle.objects.filter(
                code__iexact=code,
                operator_id=operator_id,
            ).order_by("id")

            if vehicles.count() < 2:
                continue

            # Keep the vehicle with the most data (prioritize vehicles with reg, livery, etc.)
            # This ensures we keep the detailed vehicle (from bustimes import) over the tracking-only one
            def score_vehicle(v):
                score = 0
                if v.reg:
                    score += 10
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
                f"\nFound {vehicles.count()} vehicles with code '{code}' "
                f"and operator {operator_id}:"
            )
            for v in vehicles:
                self.stdout.write(f"  - {v.slug} (id={v.id}, reg={v.reg}, withdrawn={v.withdrawn})")

            for duplicate_vehicle in vehicles_to_merge:
                # Merge logic (same as admin merge_all_selected)
                if dry_run:
                    self.stdout.write(
                        f"[DRY RUN] Would merge {duplicate_vehicle.slug} into {vehicle_to_keep.slug}"
                    )
                    total_merged += 1
                else:
                    # Move related objects
                    duplicate_vehicle.vehiclejourney_set.update(vehicle=vehicle_to_keep)
                    duplicate_vehicle.vehiclecode_set.update(vehicle=vehicle_to_keep)
                    duplicate_vehicle.vehiclerevision_set.update(vehicle=vehicle_to_keep)

                    # Ensure the slug is preserved as a vehicle code
                    with contextlib.suppress(IntegrityError):
                        VehicleCode.objects.create(
                            vehicle=vehicle_to_keep, scheme="slug", code=vehicle_to_keep.slug
                        )

                    # Copy fields from duplicate if they're better
                    if not vehicle_to_keep.slug or duplicate_vehicle.slug:
                        vehicle_to_keep.slug = duplicate_vehicle.slug
                    if not vehicle_to_keep.code or duplicate_vehicle.code:
                        vehicle_to_keep.code = duplicate_vehicle.code

                    # Keep the most recent journey
                    if not vehicle_to_keep.latest_journey_id or (
                        duplicate_vehicle.latest_journey_id
                        and duplicate_vehicle.latest_journey_id > vehicle_to_keep.latest_journey_id
                    ):
                        vehicle_to_keep.latest_journey = duplicate_vehicle.latest_journey

                    # If the kept vehicle is withdrawn but the duplicate isn't, restore it
                    if vehicle_to_keep.withdrawn and not duplicate_vehicle.withdrawn:
                        vehicle_to_keep.fleet_code = duplicate_vehicle.fleet_code
                        vehicle_to_keep.fleet_number = duplicate_vehicle.fleet_number
                        vehicle_to_keep.withdrawn = False

                    # Copy other fields if the kept vehicle doesn't have them
                    if not vehicle_to_keep.reg and duplicate_vehicle.reg:
                        vehicle_to_keep.reg = duplicate_vehicle.reg
                    if not vehicle_to_keep.livery_id and duplicate_vehicle.livery_id:
                        vehicle_to_keep.livery = duplicate_vehicle.livery
                    if not vehicle_to_keep.vehicle_type_id and duplicate_vehicle.vehicle_type_id:
                        vehicle_to_keep.vehicle_type = duplicate_vehicle.vehicle_type
                    if not vehicle_to_keep.colours and duplicate_vehicle.colours:
                        vehicle_to_keep.colours = duplicate_vehicle.colours
                    if not vehicle_to_keep.branding and duplicate_vehicle.branding:
                        vehicle_to_keep.branding = duplicate_vehicle.branding

                    # Delete the duplicate
                    duplicate_id = duplicate_vehicle.id
                    duplicate_slug = duplicate_vehicle.slug
                    duplicate_vehicle.delete()

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

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Merged {duplicate_slug} (id={duplicate_id}) into {vehicle_to_keep.slug}"
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
