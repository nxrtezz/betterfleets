from django.core.management.base import BaseCommand
from tqdm import tqdm

from busstops.bustimes_sync import BustimesApiClient, compact_text
from vehicles.models import VehicleType


class Command(BaseCommand):
    help = "Import all vehicle types from bustimes.org/api/vehicletype - field by field"

    def handle(self, *args, **options):
        client = BustimesApiClient()
        self.stdout.write("Importing vehicle types from bustimes.org/api/vehicletype...")

        created = updated = 0

        vehicle_types_data = list(client.iter_results("vehicletypes/"))

        self.stdout.write(f"Fetched {len(vehicle_types_data)} vehicle types from API")

        if not vehicle_types_data:
            self.stdout.write(self.style.WARNING("No vehicle types returned from API"))
            return

        progress = tqdm(
            vehicle_types_data,
            desc="Processing vehicle types",
            unit="vehicle type",
            file=self.stdout,
            disable=not vehicle_types_data,
        )

        for item in progress:
            try:
                # Get external_id
                external_id = compact_text(item.get("id")) or None

                # Get ALL fields from the API item
                name = compact_text(item.get("name"))
                style = compact_text(item.get("style"))
                fuel = compact_text(item.get("fuel"))
                company = compact_text(item.get("company"))
                active_production = bool(item.get("active_production", False))
                slug = compact_text(item.get("slug"))

                # Try to find existing vehicle type by external_id or name
                vehicle_type = None
                if external_id:
                    vehicle_type = VehicleType.objects.filter(external_id=external_id).first()
                if not vehicle_type and name:
                    vehicle_type = VehicleType.objects.filter(name__iexact=name).first()

                # Build values dict
                values = {
                    "name": name,
                    "style": style,
                    "fuel": fuel,
                    "company": company,
                    "active_production": active_production,
                }

                if external_id:
                    values["external_id"] = external_id
                if slug:
                    values["slug"] = slug

                if vehicle_type:
                    # Update ALL fields
                    for field, value in values.items():
                        if value is not None:
                            setattr(vehicle_type, field, value)
                    vehicle_type.save()
                    updated += 1
                else:
                    # Create new vehicle type with ALL fields
                    vehicle_type = VehicleType.objects.create(**values)
                    created += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing vehicle type: {e}"))
                continue

        self.stdout.write(
            f"Vehicle types import complete: {created} created, {updated} updated"
        )
