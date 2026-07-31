from django.core.management.base import BaseCommand
from vehicles.models import Vehicle


class Command(BaseCommand):
    help = "Delete duplicate vehicles that are withdrawn when an in-service vehicle with the same registration exists."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # Find all withdrawn vehicles with a registration
        withdrawn_vehicles = Vehicle.objects.filter(withdrawn=True).exclude(reg="")

        self.stdout.write(f"Found {withdrawn_vehicles.count()} withdrawn vehicles with registrations")

        vehicles_to_delete = []

        for vehicle in withdrawn_vehicles:
            # Check if there's another vehicle with the same registration that is NOT withdrawn
            # (i.e., in service)
            duplicate_in_service = Vehicle.objects.filter(
                reg__iexact=vehicle.reg,
                withdrawn=False
            ).exclude(id=vehicle.id).exists()

            if duplicate_in_service:
                vehicles_to_delete.append(vehicle)
                self.stdout.write(
                    f"  Would delete: {vehicle} (reg: {vehicle.reg}, id: {vehicle.id})"
                )

        if not vehicles_to_delete:
            self.stdout.write(self.style.SUCCESS("No duplicate vehicles to delete"))
            return

        self.stdout.write(
            f"\nTotal vehicles to delete: {len(vehicles_to_delete)}"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run - no vehicles were deleted"))
        else:
            # Delete the vehicles
            for vehicle in vehicles_to_delete:
                vehicle.delete()

            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully deleted {len(vehicles_to_delete)} duplicate vehicle(s)"
                )
            )
