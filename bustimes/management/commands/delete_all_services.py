from django.core.management.base import BaseCommand
from busstops.models import Service
from bustimes.models import Route, Trip
from vehicles.models import VehicleJourney

class Command(BaseCommand):
    help = "Delete all services and routes"

    def handle(self, *args, **options):
        journey_count = VehicleJourney.objects.all().count()
        VehicleJourney.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {journey_count} vehicle journeys"))

        trip_count = Trip.objects.all().count()
        Trip.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {trip_count} trips"))

        route_count = Route.objects.all().count()
        Route.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {route_count} routes"))

        service_count = Service.objects.all().count()
        Service.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {service_count} services"))
