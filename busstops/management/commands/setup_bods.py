from django.core.management.base import BaseCommand
from busstops.models import DataSource, Operator
from bustimes.models import TimetableDataSource


class Command(BaseCommand):
    help = "Setup BODS data sources for common UK operators"

    BODS_OPERATORS = [
        ("ANEA", "Arriva"),
        ("BLUS", "Bluestar"),
        ("FLIX", "Flixbus"),
        ("GNTC", "Go North East"),
        ("HANT", "Stagecoach Hampshire"),
        ("METR", "Metrobus"),
        ("NATX", "National Express"),
        ("NWRC", "First Greater Manchester"),
        ("OXBC", "Oxford Bus Company"),
        ("SCLK", "Scottish Citylink"),
        ("SCTY", "Stagecoach"),
        ("THTR", "Thames Travel"),
        ("TRNW", "Transdev Blazefield"),
        ("TFL", "Transport for London"),
        ("WBTR", "West Midlands Travel"),
    ]

    def handle(self, *args, **options):
        # Create DataSource for BODS
        ds, created = DataSource.objects.get_or_create(
            name="BODS",
            defaults={"url": "https://data.bus-data.dft.gov.uk/api/v1"}
        )
        if created:
            self.stdout.write(self.style.SUCCESS("Created BODS DataSource"))

        # Create DataSource for BODS AVL
        avl_ds, avl_created = DataSource.objects.get_or_create(
            name="BODS AVL",
            defaults={"url": "https://data.bus-data.dft.gov.uk/avl/download/"}
        )
        if avl_created:
            self.stdout.write(self.style.SUCCESS("Created BODS AVL DataSource"))

        # Create TimetableDataSources for common operators
        for noc, name in self.BODS_OPERATORS:
            # Try to get or create the operator
            operator, op_created = Operator.objects.get_or_create(
                noc=noc,
                defaults={"name": name}
            )
            if op_created:
                self.stdout.write(self.style.WARNING(f"Created operator: {name} ({noc})"))

            # Create or update TimetableDataSource
            tds, tds_created = TimetableDataSource.objects.get_or_create(
                name=f"{name} (BODS)",
                defaults={
                    "search": noc,
                    "active": True,
                }
            )
            if tds_created:
                self.stdout.write(self.style.SUCCESS(f"Created TimetableDataSource: {name}"))
                tds.operators.add(operator)
            else:
                # Add operator if not already linked
                if not tds.operators.filter(id=operator.id).exists():
                    tds.operators.add(operator)
                    self.stdout.write(self.style.SUCCESS(f"Linked operator to TimetableDataSource: {name}"))

        self.stdout.write(self.style.SUCCESS("\nBODS setup complete!"))
        self.stdout.write("\nNext steps:")
        self.stdout.write("1. Import timetables: python manage.py import_bod_timetables")
        self.stdout.write("2. Start AVL worker: python manage.py import_bod_avl --immediate")
