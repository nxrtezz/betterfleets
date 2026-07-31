from django.core.management.base import BaseCommand
from django.db import transaction
from vehicles.models import Vehicle, VehicleType


class Command(BaseCommand):
    help = "Convert ADL Enviro400 vehicles manufactured before 2006 to Dennis Trident ADL Enviro400"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without actually changing it",
        )
        parser.add_argument(
            "--new-type-name",
            default="Dennis Trident ADL Enviro400",
            help="The new vehicle type name to use (default: 'Dennis Trident ADL Enviro400')",
        )
        parser.add_argument(
            "--year-threshold",
            type=int,
            default=2009,
            help="Manufacture year threshold (default: 2009, vehicles before this year will be updated)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        new_type_name = options["new_type_name"]
        year_threshold = options["year_threshold"]
        
        # Find or create the target vehicle type
        new_type, created = VehicleType.objects.get_or_create(
            name=new_type_name,
            defaults={
                'style': 'double decker',
                'fuel': 'diesel',
            }
        )
        
        if created:
            self.stdout.write(
                self.style.SUCCESS(f"Created new vehicle type: {new_type_name}")
            )
        else:
            self.stdout.write(f"Using existing vehicle type: {new_type_name}")

        # First, show all vehicle types containing "Enviro400" for debugging
        enviro_types = VehicleType.objects.filter(name__icontains="Enviro400")
        self.stdout.write(f"\nVehicle types containing 'Enviro400': {enviro_types.count()}")
        for vt in enviro_types:
            self.stdout.write(f"  - {vt.name} (id: {vt.id})")

        # Find vehicles to update
        # Look for vehicles with vehicle_type name containing "ADL Enviro400" and year_of_manufacture < year_threshold
        vehicles_to_update = Vehicle.objects.filter(
            vehicle_type__name__icontains="ADL Enviro400",
            year_of_manufacture__lt=year_threshold,
        ).select_related('vehicle_type')

        count = vehicles_to_update.count()
        
        # Also count total ADL Enviro400 vehicles
        total_adl_enviro = Vehicle.objects.filter(
            vehicle_type__name__icontains="ADL Enviro400"
        ).count()
        self.stdout.write(f"\nTotal ADL Enviro400 vehicles: {total_adl_enviro}")
        self.stdout.write(f"ADL Enviro400 vehicles before {year_threshold}: {count}")
        
        if count == 0:
            self.stdout.write(self.style.WARNING("No vehicles found matching the criteria"))
            return

        self.stdout.write(f"Found {count} vehicle(s) to update")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run - no changes will be made"))
            for vehicle in vehicles_to_update:
                self.stdout.write(
                    f"  Would update: {vehicle} (current type: {vehicle.vehicle_type.name}, "
                    f"year: {vehicle.year_of_manufacture}) -> {new_type_name}"
                )
            
            # Also show all ADL Enviro400 vehicles for debugging
            all_adl_enviro = Vehicle.objects.filter(
                vehicle_type__name__icontains="ADL Enviro400"
            ).select_related('vehicle_type')
            self.stdout.write(f"\nAll ADL Enviro400 vehicles in database: {all_adl_enviro.count()}")
            for vehicle in all_adl_enviro:
                self.stdout.write(
                    f"  {vehicle} (type: {vehicle.vehicle_type.name}, year: {vehicle.year_of_manufacture})"
                )
            return

        # Perform the update
        with transaction.atomic():
            updated = vehicles_to_update.update(vehicle_type=new_type)
        
        self.stdout.write(
            self.style.SUCCESS(f"Successfully updated {updated} vehicle(s) to {new_type_name}")
        )
