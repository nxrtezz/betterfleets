"""Delete all services not from BODS (Bus Open Data Service) sources"""

from django.core.management.base import BaseCommand

from busstops.models import DataSource, Service
from bustimes.models import Route
from vehicles.models import VehicleJourney


class Command(BaseCommand):
    help = "Delete all services not from BODS (Bus Open Data Service) sources"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="Show what would be deleted without deleting"
        )

    def handle(self, dry_run=False, **options):
        # Get all non-BODS data sources
        # BODS sources have URLs ending with .bus-data.dft.gov.uk
        non_bods_sources = DataSource.objects.exclude(
            url__endswith=".bus-data.dft.gov.uk"
        ).exclude(
            url__endswith=".bus-data.dft.gov.uk/"
        )

        if non_bods_sources.count() == 0:
            self.stdout.write(self.style.WARNING("No non-BODS sources found"))
            return

        self.stdout.write(f"Found {non_bods_sources.count()} non-BODS sources:")
        for source in non_bods_sources:
            self.stdout.write(f"  - {source.name} ({source.url})")

        # Get all services from non-BODS sources
        services = Service.objects.filter(source__in=non_bods_sources)
        service_count = services.count()

        if service_count == 0:
            self.stdout.write(self.style.WARNING("No services from non-BODS sources found"))
            return

        self.stdout.write(f"Found {service_count} services from non-BODS sources")

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

        if not input("Are you sure you want to delete all non-BODS services? (yes/no): ").lower() == "yes":
            self.stdout.write(self.style.WARNING("Aborted"))
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

        # Finally delete the non-BODS sources
        deleted_sources, _ = non_bods_sources.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_sources} data sources"))

        self.stdout.write(self.style.SUCCESS("Done"))
