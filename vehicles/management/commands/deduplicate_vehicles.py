from django.core.management.base import BaseCommand
from django.db.models import Q
from vehicles.models import Vehicle, VehicleJourney, VehicleCode


class Command(BaseCommand):
    help = (
        "Automatically deduplicate vehicles by merging ticket machines (vehicles without livery or type) "
        "with their proper vehicles (vehicles with livery or type) when they have the same registration "
        "within the same operator. Copies the code from the ticket machine to the proper vehicle before merging."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be merged without actually merging",
        )
        parser.add_argument(
            "--operator",
            help="Only process a specific operator (by NOC)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        specific_operator = options.get("operator")

        # Build query for vehicles to process
        vehicles = Vehicle.objects.filter(preserved=False)

        if specific_operator:
            vehicles = vehicles.filter(operator__noc=specific_operator)

        total_merged = 0
        total_skipped = 0

        self.stdout.write("Finding duplicate vehicles with same registration...")

        # Group vehicles by operator and registration
        vehicles_with_reg = vehicles.exclude(reg="").exclude(reg__isnull=True)

        for vehicle in vehicles_with_reg.order_by("id"):
            # Find duplicates with same registration and operator
            duplicates = Vehicle.objects.filter(
                operator=vehicle.operator_id,
                reg__iexact=vehicle.reg,
                preserved=False,
                id__lt=vehicle.id,  # Only look at vehicles with lower ID
            )

            if not duplicates.exists():
                continue

            duplicate = duplicates.first()

            # Check if one is a ticket machine (no livery and no type)
            is_vehicle_ticket_machine = not vehicle.livery_id and not vehicle.vehicle_type_id
            is_duplicate_ticket_machine = not duplicate.livery_id and not duplicate.vehicle_type_id

            ticket_machine = None
            proper_vehicle = None

            if is_vehicle_ticket_machine and not is_duplicate_ticket_machine:
                # vehicle is ticket machine, duplicate is proper vehicle
                ticket_machine = vehicle
                proper_vehicle = duplicate
            elif not is_vehicle_ticket_machine and is_duplicate_ticket_machine:
                # duplicate is ticket machine, vehicle is proper vehicle
                ticket_machine = duplicate
                proper_vehicle = vehicle
            else:
                # Both are ticket machines or both are proper vehicles
                # Skip for now, let manual deduplication handle these
                total_skipped += 1
                continue

            if not ticket_machine or not proper_vehicle:
                total_skipped += 1
                continue

            self.stdout.write(
                f"\nFound: {ticket_machine} (ticket machine, code: {ticket_machine.code}) "
                f"and {proper_vehicle} (proper vehicle, code: {proper_vehicle.code})"
            )

            # Copy code from ticket machine to proper vehicle if ticket machine has a code
            if ticket_machine.code and not proper_vehicle.code:
                self.stdout.write(
                    f"  Copying code '{ticket_machine.code}' from ticket machine to proper vehicle"
                )
                if not dry_run:
                    proper_vehicle.code = ticket_machine.code
                    proper_vehicle.save(update_fields=["code"])

            # Merge them (keep proper_vehicle, delete ticket_machine)
            if not dry_run:
                try:
                    # Move journeys from ticket machine to proper vehicle
                    VehicleJourney.objects.filter(vehicle=ticket_machine).update(vehicle=proper_vehicle)

                    # Move VehicleCode records from ticket machine to proper vehicle
                    ticket_machine_codes = VehicleCode.objects.filter(vehicle=ticket_machine)
                    for code in ticket_machine_codes:
                        code.vehicle = proper_vehicle
                        code.save()

                    # Copy fleet code and fleet number if proper vehicle doesn't have them
                    if ticket_machine.fleet_code and not proper_vehicle.fleet_code:
                        proper_vehicle.fleet_code = ticket_machine.fleet_code
                    if ticket_machine.fleet_number and not proper_vehicle.fleet_number:
                        proper_vehicle.fleet_number = ticket_machine.fleet_number

                    # Update withdrawn status
                    if proper_vehicle.withdrawn and not ticket_machine.withdrawn:
                        proper_vehicle.withdrawn = False

                    # Save proper vehicle
                    proper_vehicle.save(
                        update_fields=["fleet_code", "fleet_number", "withdrawn"]
                    )

                    # Delete ticket machine
                    ticket_machine.delete()

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  Merged: {ticket_machine} deleted, data moved to {proper_vehicle}"
                        )
                    )
                    total_merged += 1
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"  Error merging: {e}")
                    )
            else:
                self.stdout.write(f"  [DRY RUN] Would merge ticket machine into proper vehicle")
                total_merged += 1

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"Total vehicles merged: {total_merged}")
        self.stdout.write(f"Total skipped (both ticket machines or both proper): {total_skipped}")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run - no vehicles were actually merged"))
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Successfully merged {total_merged} vehicle(s)")
            )
