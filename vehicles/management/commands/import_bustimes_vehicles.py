import requests
from django.core.management.base import BaseCommand
from busstops.models import Operator, DataSource
from vehicles.models import Vehicle, VehicleType, Livery

class Command(BaseCommand):
    help = "Import all vehicles from bustimes.org API"

    def handle(self, *args, **options):
        source, _ = DataSource.objects.get_or_create(
            name="bustimes.org",
            defaults={"url": "https://bustimes.org"}
        )

        # First import vehicle types
        self.stdout.write("Importing vehicle types...")
        self.import_vehicle_types()

        # Then import liveries
        self.stdout.write("\nImporting liveries...")
        self.import_liveries()

        # Then import vehicles
        self.stdout.write("\nImporting vehicles...")
        self.import_vehicles(source)

    def import_vehicle_types(self):
        url = "https://bustimes.org/api/vehicletypes/"
        count = 0

        while url:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            data = response.json()

            for vt_data in data["results"]:
                # Map API fields to model fields
                # API has: name, style, fuel, double_decker, coach, electric
                # Model has: name, style (choice), fuel (choice)
                style = vt_data.get("style", "")
                fuel = vt_data.get("fuel", "")

                # Convert boolean fields to style choices if needed
                if not style:
                    if vt_data.get("double_decker"):
                        style = "double decker"
                    elif vt_data.get("coach"):
                        style = "coach"
                    elif vt_data.get("electric"):
                        # electric alone doesn't determine style
                        pass

                vehicle_type, created = VehicleType.objects.update_or_create(
                    id=vt_data["id"],
                    defaults={
                        "name": vt_data["name"],
                        "style": style,
                        "fuel": fuel,
                    }
                )
                if created:
                    count += 1

            url = data.get("next")

        self.stdout.write(self.style.SUCCESS(f"Imported {count} vehicle types"))

    def import_liveries(self):
        url = "https://bustimes.org/api/liveries/"
        count = 0

        while url:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            data = response.json()

            for liv_data in data["results"]:
                livery, created = Livery.objects.update_or_create(
                    id=liv_data["id"],
                    defaults={
                        "name": liv_data["name"],
                        "left_css": liv_data.get("left_css", ""),
                        "right_css": liv_data.get("right_css", ""),
                        "white_text": liv_data.get("white_text", False),
                        "text_colour": liv_data.get("text_colour", ""),
                        "stroke_colour": liv_data.get("stroke_colour", ""),
                        "published": True,  # Import from bustimes.org should be published
                    }
                )
                if created:
                    count += 1

            url = data.get("next")

        self.stdout.write(self.style.SUCCESS(f"Imported {count} liveries"))

    def import_vehicles(self, source):
        url = "https://bustimes.org/api/vehicles/"
        count = 0
        updated = 0

        while url:
            self.stdout.write(f"Fetching {url}...")
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            data = response.json()

            for veh_data in data["results"]:
                fleet_number = veh_data.get("fleet_number")
                fleet_code = veh_data.get("fleet_code")
                reg = veh_data.get("reg")
                previous_reg = veh_data.get("previous_reg", "")
                name = veh_data.get("name", "")
                notes = veh_data.get("notes", "")
                withdrawn = veh_data.get("withdrawn", False)

                # Get operator
                operator = None
                if veh_data.get("operator"):
                    operator = Operator.objects.filter(
                        noc=veh_data["operator"]["id"]
                    ).first()

                # Get vehicle type
                vehicle_type = None
                if veh_data.get("vehicle_type"):
                    vehicle_type = VehicleType.objects.filter(
                        id=veh_data["vehicle_type"]["id"]
                    ).first()

                # Get livery
                livery = None
                if veh_data.get("livery"):
                    livery = Livery.objects.filter(
                        id=veh_data["livery"]["id"]
                    ).first()

                vehicle, created = Vehicle.objects.update_or_create(
                    id=veh_data["id"],
                    defaults={
                        "code": reg or fleet_code or str(veh_data["id"]),
                        "fleet_number": fleet_number,
                        "fleet_code": fleet_code or "",
                        "reg": reg or "",
                        "name": name,
                        "notes": notes,
                        "withdrawn": withdrawn,
                        "operator": operator,
                        "vehicle_type": vehicle_type,
                        "livery": livery,
                        "source": source,
                    }
                )

                if created:
                    self.stdout.write(self.style.SUCCESS(f"Created vehicle: {reg or fleet_code}"))
                    count += 1
                else:
                    updated += 1

            url = data.get("next")

        self.stdout.write(self.style.SUCCESS(f"\nImported {count} vehicles, updated {updated}"))
