from django.core.management.base import BaseCommand
from tqdm import tqdm

from busstops.bustimes_sync import BustimesApiClient, compact_text, apply_sync_fields, api_id
from vehicles.models import VehicleType
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = "Import all vehicle types from bustimes.org/api/vehicletype - field by field"

    def handle(self, *args, **options):
        client = BustimesApiClient()
        self.stdout.write("Importing vehicle types from bustimes.org/api/vehicletype...")

        # Get admin user for data change logs
        admin_user = User.objects.filter(is_superuser=True).first()
        if not admin_user:
            self.stdout.write(self.style.WARNING("No admin user found, data changes will not be attributed"))
            admin_user = None

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
                external_id = api_id(item)

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

                # Remove None values
                values = {k: v for k, v in values.items() if v is not None}

                if vehicle_type:
                    # Update using apply_sync_fields with admin user
                    result = apply_sync_fields(
                        instance=vehicle_type,
                        object_type="vehicletype",
                        external_id=external_id or name,
                        values=values,
                        payload=item,
                        dry_run=False,
                        force=True,
                        source="bustimes_sync:vehicletype",
                        user=admin_user,
                    )
                    if result.created:
                        created += 1
                    if result.updated:
                        updated += 1
                else:
                    # Create new vehicle type
                    vehicle_type = VehicleType()
                    for field, value in values.items():
                        setattr(vehicle_type, field, value)
                    vehicle_type.save()
                    created += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing vehicle type: {e}"))
                continue

        self.stdout.write(
            f"Vehicle types import complete: {created} created, {updated} updated"
        )
