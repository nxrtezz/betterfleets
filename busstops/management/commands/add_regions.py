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
            ("RE", "Republic of Ireland"),
            ("IO", "Islands of Scotland"),
            ("WA", "Wales"),
            ("SC", "Scotland"),
            ("YO", "Yorkshire and the Humber"),
            ("LO", "London"),
            ("AD", "Aldershot"),
            ("AN", "Anglia"),
            ("BG", "Borders"),
            ("BR", "Bristol"),
            ("CM", "Cambridge"),
            ("CT", "Cotswolds"),
            ("CV", "Cumbria"),
            ("DB", "Derbyshire"),
            ("DU", "Durham"),
            ("ES", "Essex"),
            ("GL", "Gloucestershire"),
            ("GS", "Glasgow"),
            ("HX", "Hampshire"),
            ("KE", "Kent"),
            ("LA", "Lancashire"),
            ("LE", "Leeds"),
            ("LI", "Lincolnshire"),
            ("LN", "London"),
            ("ME", "Merseyside"),
            ("NC", "Northumberland"),
            ("NK", "Northamptonshire"),
            ("NT", "Nottinghamshire"),
            ("OX", "Oxfordshire"),
            ("SO", "Somerset"),
            ("SR", "Surrey"),
            ("SS", "Southampton"),
            ("ST", "Staffordshire"),
            ("SU", "Suffolk"),
            ("TE", "Teeside"),
            ("WA", "Wales"),
            ("WD", "Wiltshire"),
            ("WS", "West Sussex"),
            ("WW", "Warwickshire"),
            ("YK", "Yorkshire"),
        ]

        for region_id, name in regions:
            region, created = Region.objects.get_or_create(
                id=region_id,
                defaults={"name": name}
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created region: {name}"))
            else:
                self.stdout.write(self.style.WARNING(f"Region already exists: {name}"))

        self.stdout.write(self.style.SUCCESS("Regions added successfully!"))
