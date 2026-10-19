"""Delete all services and routes for a specific operator"""

from django.core.management.base import BaseCommand
from django.db.models import Q

from busstops.models import Operator, Service
from bustimes.models import Route


class Command(BaseCommand):
    help = "Delete all services and routes for a specific operator"

    def add_arguments(self, parser):
        parser.add_argument("noc", type=str, help="Operator NOC code")
        parser.add_argument(
            "--dry-run", action="store_true", help="Show what would be deleted without deleting"
        )

    def handle(self, noc, dry_run=False, **options):
        operator = Operator.objects.filter(noc=noc).first()
        if not operator:
            self.stdout.write(self.style.ERROR(f"Operator with NOC {noc} not found"))
            return

        self.stdout.write(f"Deleting services for {operator.name} ({noc})")

        # Get all services for this operator
        services = Service.objects.filter(operator=operator)
        service_count = services.count()

        # Get all routes for these services
        routes = Route.objects.filter(service__in=services)
        route_count = routes.count()

        self.stdout.write(f"Found {service_count} services and {route_count} routes")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes made"))
            return

        # Delete routes first (they have foreign key to service)
        deleted_routes, _ = routes.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_routes} routes"))

        # Then delete services
        deleted_services, _ = services.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_services} services"))

        self.stdout.write(self.style.SUCCESS("Done"))
