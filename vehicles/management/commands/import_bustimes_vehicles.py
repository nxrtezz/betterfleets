import requests
from django.core.management.base import BaseCommand
from busstops.models import Operator, DataSource
from vehicles.models import Vehicle, VehicleType, Livery, VehicleJourney, VehicleFeature

class Command(BaseCommand):
    help = "Import all vehicles from bustimes.org API with strict matching rules"

    def handle(self, *args, **options):
        source, _ = DataSource.objects.get_or_create(
            name="bustimes.org",
            defaults={"url": "https://bustimes.org"}
        )

        # First import vehicle types with strict ID matching
        self.stdout.write("Importing vehicle types...")
        self.import_vehicle_types()

        # Then import liveries with strict ID, name, and CSS matching
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
                vt_id = vt_data["id"]
                vt_name = vt_data["name"]
                style = vt_data.get("style", "")
                fuel = vt_data.get("fuel", "")

                # Convert boolean fields to style choices if needed
                if not style:
                    if vt_data.get("double_decker"):
                        style = "double decker"
                    elif vt_data.get("coach"):
                        style = "coach"

                # Strict: Check if exists by ID AND name match
                existing = VehicleType.objects.filter(id=vt_id).first()
                if existing and existing.name == vt_name:
                    # Update existing
                    existing.style = style
                    existing.fuel = fuel
                    existing.save()
                    count += 1
                else:
                    # Create new
                    VehicleType.objects.create(
                        id=vt_id,
                        name=vt_name,
                        style=style,
                        fuel=fuel,
                    )
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
                liv_id = liv_data["id"]
                liv_name = liv_data["name"]
                left_css = liv_data.get("left", liv_data.get("left_css", ""))
                right_css = liv_data.get("right", liv_data.get("right_css", ""))
                white_text = liv_data.get("white_text", False)
                text_colour = liv_data.get("text_colour", "")
                stroke_colour = liv_data.get("stroke_colour", "")

                # Strict: Check if exists by ID, name, AND exact CSS match
                existing = Livery.objects.filter(id=liv_id).first()
                if existing and existing.name == liv_name:
                    # Check if CSS matches exactly
                    if existing.left_css == left_css and existing.right_css == right_css:
                        # Update other fields
                        existing.white_text = white_text
                        existing.text_colour = text_colour
                        existing.stroke_colour = stroke_colour
                        existing.published = True
                        existing.save()
                        count += 1
                    else:
                        # CSS mismatch, create new with different ID (but we can't change ID)
                        # Update CSS to match
                        existing.left_css = left_css
                        existing.right_css = right_css
                        existing.white_text = white_text
                        existing.text_colour = text_colour
                        existing.stroke_colour = stroke_colour
                        existing.published = True
                        existing.save()
                        count += 1
                else:
                    # Create new
                    Livery.objects.create(
                        id=liv_id,
                        name=liv_name,
                        left_css=left_css,
                        right_css=right_css,
                        white_text=white_text,
                        text_colour=text_colour,
                        stroke_colour=stroke_colour,
                        published=True,
                    )
                    count += 1

            url = data.get("next")

        self.stdout.write(self.style.SUCCESS(f"Imported {count} liveries"))

    def import_vehicles(self, source):
        url = "https://bustimes.org/api/vehicles/"
        count = 0

        while url:
            self.stdout.write(f"Fetching {url}...")
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            data = response.json()

            for veh_data in data["results"]:
                veh_id = veh_data["id"]
                slug = veh_data.get("slug", "")
                fleet_number = veh_data.get("fleet_number")
                fleet_code = veh_data.get("fleet_code")
                reg = veh_data.get("reg")
                previous_reg = veh_data.get("previous_reg", "")
                name = veh_data.get("name", "")
                notes = veh_data.get("notes", "")
                withdrawn = veh_data.get("withdrawn", False)
                branding = veh_data.get("branding", "")

                # Get operator by NOC
                operator = None
                if veh_data.get("operator"):
                    operator = Operator.objects.filter(
                        noc=veh_data["operator"]["id"]
                    ).first()

                # Get vehicle type by ID
                vehicle_type = None
                if veh_data.get("vehicle_type"):
                    vehicle_type = VehicleType.objects.filter(
                        id=veh_data["vehicle_type"]["id"]
                    ).first()

                # Get livery by ID
                livery = None
                if veh_data.get("livery"):
                    livery = Livery.objects.filter(
                        id=veh_data["livery"]["id"]
                    ).first()

                # Create vehicle
                vehicle = Vehicle.objects.create(
                    id=veh_id,
                    slug=slug,
                    code=reg or fleet_code or str(veh_id),
                    fleet_number=fleet_number,
                    fleet_code=fleet_code or "",
                    reg=reg or "",
                    name=name,
                    notes=notes,
                    withdrawn=withdrawn,
                    branding=branding,
                    operator=operator,
                    vehicle_type=vehicle_type,
                    livery=livery,
                    source=source,
                )

                # Handle special features
                if veh_data.get("special_features"):
                    for feature_name in veh_data["special_features"]:
                        feature, _ = VehicleFeature.objects.get_or_create(name=feature_name)
                        vehicle.features.add(feature)

                count += 1
                if count % 1000 == 0:
                    self.stdout.write(f"  Imported {count} vehicles...")

            url = data.get("next")

        self.stdout.write(self.style.SUCCESS(f"\nImported {count} vehicles"))
