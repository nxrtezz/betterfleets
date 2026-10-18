from django.core.management.base import BaseCommand
from busstops.models import Region


class Command(BaseCommand):
    help = "Create sample regions for BetterFleets"

    def handle(self, *args, **options):
        regions = [
            ("EA", "East Anglia"),
            ("EM", "East Midlands"),
            ("L", "London"),
            ("NE", "North East"),
            ("NW", "North West"),
            ("SE", "South East"),
            ("SW", "South West"),
            ("WM", "West Midlands"),
            ("Y", "Yorkshire"),
            ("W", "Wales"),
            ("S", "Scotland"),
            ("GB", "Great Britain"),
            ("NI", "Northern Ireland"),
            ("CO", "Connacht"),
            ("LE", "Leinster"),
            ("MU", "Munster"),
            ("UL", "Ulster"),
            ("IM", "Isle of Man"),
        ]

        for slug, name in regions:
            region, created = Region.objects.get_or_create(
                slug=slug,
                defaults={"name": name}
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created region: {name}"))
            else:
                self.stdout.write(self.style.WARNING(f"Region already exists: {name}"))

        self.stdout.write(self.style.SUCCESS("Regions added successfully!"))
