"""Clean up all data for a specific operator"""

from django.core.management.base import BaseCommand
from django.db.models import Q

from busstops.models import Operator, Service

from vehicles.models import VehicleJourney

from ...models import Route, Trip


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("noc", type=str, help="Operator NOC code")

    def handle(self, noc, *args, **options):
        try:
            operator = Operator.objects.get(noc=noc)
        except Operator.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Operator {noc} not found"))
            return

        self.stdout.write(f"Cleaning up data for {operator} ({noc})...")

        # Get all service IDs for this operator
        service_ids = Service.objects.filter(operator=operator).values_list("id", flat=True)

        # Delete trips for routes belonging to these services
        trip_count = Trip.objects.filter(route__service__in=service_ids).delete()[0]
        self.stdout.write(f"Deleted {trip_count} trips")

        # Delete routes for these services
        route_count = Route.objects.filter(service__in=service_ids).delete()[0]
        self.stdout.write(f"Deleted {route_count} routes")

        # Delete vehicle journeys for these services
        vj_count = VehicleJourney.objects.filter(service__in=service_ids).delete()[0]
        self.stdout.write(f"Deleted {vj_count} vehicle journeys")

        # Delete services
        service_count = Service.objects.filter(operator=operator).delete()[0]
        self.stdout.write(f"Deleted {service_count} services")

        self.stdout.write(self.style.SUCCESS(f"Cleaned up {operator}"))
