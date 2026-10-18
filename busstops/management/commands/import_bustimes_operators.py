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
        updated = 0

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

                # Handle slug conflicts
                operator = Operator.objects.filter(noc=noc).first()
                if operator:
                    # Update existing operator, keep existing slug to avoid conflicts
                    operator.name = name
                    operator.vehicle_mode = vehicle_mode
                    if region_id:
                        operator.region_id = region_id
                    operator.url = op_url
                    operator.twitter = twitter
                    operator.source = source
                    operator.save()
                    self.stdout.write(self.style.WARNING(f"Updated operator: {name} ({noc})"))
                    updated += 1
                else:
                    # Create new operator
                    # Handle slug conflict if needed
                    final_slug = slug
                    if Operator.objects.filter(slug=slug).exists():
                        suffix = 1
                        while Operator.objects.filter(slug=f"{slug}-{suffix}").exists():
                            suffix += 1
                        final_slug = f"{slug}-{suffix}"

                    operator = Operator.objects.create(
                        noc=noc,
                        name=name,
                        slug=final_slug,
                        vehicle_mode=vehicle_mode,
                        region_id=region_id,
                        url=op_url,
                        twitter=twitter,
                        source=source,
                    )
                    self.stdout.write(self.style.SUCCESS(f"Created operator: {name} ({noc})"))
                    count += 1

            url = data.get("next")

        self.stdout.write(self.style.SUCCESS(f"\nImported {count} operators, updated {updated} from bustimes.org"))
