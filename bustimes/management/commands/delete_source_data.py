"""Delete all data from a specific DataSource (e.g., from a TransXChange import)"""

from django.core.management.base import BaseCommand

from busstops.models import DataSource, Service
from bustimes.models import Route
from vehicles.models import VehicleJourney


class Command(BaseCommand):
    help = "Delete all data from a specific DataSource"

    def add_arguments(self, parser):
        parser.add_argument("source_name", type=str, help="DataSource name (e.g., BLAC-27102026)")
        parser.add_argument(
            "--dry-run", action="store_true", help="Show what would be deleted without deleting"
        )

    def handle(self, source_name, dry_run=False, **options):
        source = DataSource.objects.filter(name=source_name).first()
        if not source:
            self.stdout.write(self.style.ERROR(f"DataSource with name {source_name} not found"))
            return

        self.stdout.write(f"Deleting data from {source.name}")

        # Get all services from this source
        services = Service.objects.filter(source=source)
        service_count = services.count()

        # Get all routes for these services
        routes = Route.objects.filter(service__in=services)
        route_count = routes.count()

        # Get all vehicle journeys for these services
        vehicle_journeys = VehicleJourney.objects.filter(service__in=services)
        vj_count = vehicle_journeys.count()

        self.stdout.write(
            f"Found {service_count} services, {route_count} routes, and {vj_count} vehicle journeys"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes made"))
            return

        # Delete vehicle journeys first (they have foreign key to service)
        deleted_vj, _ = vehicle_journeys.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_vj} vehicle journeys"))

        # Delete routes (they have foreign key to service)
        deleted_routes, _ = routes.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_routes} routes"))

        # Then delete services
        deleted_services, _ = services.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_services} services"))

        # Finally delete the source
        source.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted DataSource {source_name}"))

        self.stdout.write(self.style.SUCCESS("Done"))
