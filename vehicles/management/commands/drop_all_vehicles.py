from django.core.management.base import BaseCommand
from vehicles.models import Vehicle, VehicleType, Livery, VehicleJourney, VehicleFeature

class Command(BaseCommand):
    help = "Drop all vehicles, vehicle types, liveries, and related data"

    def handle(self, *args, **options):
        # Delete in order of dependencies
        feature_count = VehicleFeature.objects.count()
        VehicleFeature.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {feature_count} vehicle features"))

        journey_count = VehicleJourney.objects.count()
        VehicleJourney.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {journey_count} vehicle journeys"))

        vehicle_count = Vehicle.objects.count()
        Vehicle.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {vehicle_count} vehicles"))

        livery_count = Livery.objects.count()
        Livery.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {livery_count} liveries"))

        type_count = VehicleType.objects.count()
        VehicleType.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {type_count} vehicle types"))
