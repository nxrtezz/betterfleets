import requests
from django.core.management.base import BaseCommand
from busstops.models import Operator, OperatorCode, DataSource, Region

class Command(BaseCommand):
    help = "Import all operators from bustimes.org API"

    def handle(self, *args, **options):
        source, _ = DataSource.objects.get_or_create(
            name="bustimes.org",
            defaults={"url": "https://bustimes.org"}
        )

        url = "https://bustimes.org/api/operators/"
        count = 0

        while url:
            self.stdout.write(f"Fetching {url}...")
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            data = response.json()

            for op_data in data["results"]:
                noc = op_data["noc"]
                name = op_data["name"]
                slug = op_data["slug"]
                vehicle_mode = op_data.get("vehicle_mode", "bus")
                region_id = op_data.get("region_id")
                op_url = op_data.get("url", "")
                twitter = op_data.get("twitter", "")

                # Check if region exists, if not set to None
                if region_id and not Region.objects.filter(id=region_id).exists():
                    region_id = None

                operator, created = Operator.objects.update_or_create(
                    noc=noc,
                    defaults={
                        "name": name,
                        "slug": slug,
                        "vehicle_mode": vehicle_mode,
                        "region_id": region_id,
                        "url": op_url,
                        "twitter": twitter,
                        "source": source,
                    }
                )

                if created:
                    self.stdout.write(self.style.SUCCESS(f"Created operator: {name} ({noc})"))
                    count += 1
                else:
                    self.stdout.write(self.style.WARNING(f"Updated operator: {name} ({noc})"))

            url = data.get("next")

        self.stdout.write(self.style.SUCCESS(f"\nImported/updated {count} operators from bustimes.org"))
