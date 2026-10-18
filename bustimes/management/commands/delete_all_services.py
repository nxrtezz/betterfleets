from django.core.management.base import BaseCommand
from busstops.models import Service

class Command(BaseCommand):
    help = "Delete all services"

    def handle(self, *args, **options):
        count = Service.objects.all().count()
        Service.objects.all().delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} services"))
