import requests
from django.core.management.base import BaseCommand


from ...models import DataSource, Service


class Command(BaseCommand):
    def handle(self, *args, **options):
        source, _ = DataSource.objects.get_or_create(name="jersey")

        response = requests.get(
            "http://sojbuslivetimespublic.azurewebsites.net/api/Values/v1/GetRoutes"
        )
        routes = response.json()["routes"]

        for item in routes:
            service, _ = Service.objects.update_or_create(
                {
                    "colour": item["Colour"],
                    "description": item["Name"].strip(),
                    "current": True,
                    "region_id": "JE",
                },
                line_name=item["Number"],
                source=source,
            )

            service.operator.set(["libertybus"])
