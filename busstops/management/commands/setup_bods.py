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
            defaults={
                "url": "https://data.bus-data.dft.gov.uk/api/v1/datafeed",
                "description": "BODS SIRI-VM AVL datafeed",
                "settings": {"bounding_box": "-6.5,50.0,2.0,55.8"}  # England bounding box
            }
        )
        if avl_created:
            self.stdout.write(self.style.SUCCESS("Created BODS AVL DataSource"))
        else:
            # Update URL if it was the old incorrect one
            if avl_ds.url != "https://data.bus-data.dft.gov.uk/api/v1/datafeed":
                avl_ds.url = "https://data.bus-data.dft.gov.uk/api/v1/datafeed"
                avl_ds.description = "BODS SIRI-VM AVL datafeed"
                if not avl_ds.settings:
                    avl_ds.settings = {"bounding_box": "-6.5,50.0,2.0,55.8"}
                elif "bounding_box" not in avl_ds.settings:
                    avl_ds.settings["bounding_box"] = "-6.5,50.0,2.0,55.8"
                avl_ds.save()
                self.stdout.write(self.style.SUCCESS("Updated BODS AVL DataSource URL"))

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
                if not tds.operators.filter(pk=operator.pk).exists():
                    tds.operators.add(operator)
                    self.stdout.write(self.style.SUCCESS(f"Linked operator to TimetableDataSource: {name}"))

        self.stdout.write(self.style.SUCCESS("\nBODS setup complete!"))
        self.stdout.write("\nNext steps:")
        self.stdout.write("1. Import timetables: python manage.py import_bod_timetables")
        self.stdout.write("2. Start AVL worker: python manage.py import_bod_avl --immediate")
