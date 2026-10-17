from django.core.management.base import BaseCommand
from tqdm import tqdm

from busstops.bustimes_sync import BustimesApiClient, compact_text, compact_registration, apply_sync_fields, api_id
from busstops.models import Operator
from vehicles.models import Vehicle, VehicleType, Livery
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = "Import all vehicles from bustimes.org/api/vehicle - field by field"

    def handle(self, *args, **options):
        client = BustimesApiClient()
        self.stdout.write("Importing vehicles from bustimes.org/api/vehicle...")

        # Get admin user for data change logs
        admin_user = User.objects.filter(is_superuser=True).first()
        if not admin_user:
            self.stdout.write(self.style.WARNING("No admin user found, data changes will not be attributed"))
            admin_user = None

        created = updated = 0

        vehicles_data = list(client.iter_results("vehicles/"))

        self.stdout.write(f"Fetched {len(vehicles_data)} vehicles from API")

        if not vehicles_data:
            self.stdout.write(self.style.WARNING("No vehicles returned from API"))
            return

        progress = tqdm(
            vehicles_data,
            desc="Processing vehicles",
            unit="vehicle",
            file=self.stdout,
            disable=not vehicles_data,
        )

        for item in progress:
            try:
                # Get fields from ACTUAL API response
                external_id = item.get("id")
                slug = compact_text(item.get("slug"))
                fleet_number = item.get("fleet_number")
                fleet_code = compact_text(item.get("fleet_code"))
                reg = compact_registration(item.get("reg"))
                previous_reg = compact_registration(item.get("previous_reg"))
                branding = compact_text(item.get("branding"))
                name = compact_text(item.get("name"))
                notes = compact_text(item.get("notes"))
                withdrawn = bool(item.get("withdrawn", False))
                special_features = item.get("special_features")

                # Handle nested objects
                operator_data = item.get("operator")
                operator = None
                if operator_data:
                    operator_noc = operator_data.get("id")
                    if operator_noc:
                        operator = Operator.objects.filter(noc=operator_noc).first()

                vehicle_type_data = item.get("vehicle_type")
                vehicle_type = None
                if vehicle_type_data:
                    vehicle_type_name = vehicle_type_data.get("name")
                    if vehicle_type_name:
                        vehicle_type = VehicleType.objects.filter(name__iexact=vehicle_type_name).first()

                livery_data = item.get("livery")
                livery = None
                if livery_data:
                    livery_id = livery_data.get("id")
                    if livery_id:
                        livery = Livery.objects.filter(external_id=str(livery_id)).first()

                # Try to find existing vehicle by external_id
                vehicle = None
                if external_id:
                    vehicle = Vehicle.objects.filter(external_id=str(external_id)).first()

                # Build values dict based on ACTUAL API fields
                values = {}

                if fleet_number:
                    values["fleet_number"] = fleet_number
                if fleet_code:
                    values["fleet_code"] = fleet_code
                if reg:
                    values["reg"] = reg
                if previous_reg:
                    values["prev_registration"] = previous_reg
                if branding:
                    values["branding"] = branding
                if name:
                    values["name"] = name
                if notes:
                    values["notes"] = notes
                if withdrawn is not None:
                    values["withdrawn"] = withdrawn

                if operator:
                    values["operator"] = operator
                if vehicle_type:
                    values["vehicle_type"] = vehicle_type
                if livery:
                    values["livery"] = livery
                if external_id:
                    values["external_id"] = str(external_id)
                if slug:
                    values["slug"] = slug

                # Remove None values
                values = {k: v for k, v in values.items() if v is not None}

                if vehicle:
                    # Update using apply_sync_fields with admin user
                    result = apply_sync_fields(
                        instance=vehicle,
                        object_type="vehicle",
                        external_id=str(external_id) if external_id else "",
                        values=values,
                        payload=item,
                        dry_run=False,
                        force=True,
                        source="bustimes_sync:vehicle",
                        user=admin_user,
                    )
                    if result.created:
                        created += 1
                    if result.updated:
                        updated += 1
                else:
                    # Create new vehicle
                    vehicle = Vehicle()
                    for field, value in values.items():
                        setattr(vehicle, field, value)
                    vehicle.save()
                    created += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing vehicle: {e}"))
                continue

        self.stdout.write(
            f"Vehicles import complete: {created} created, {updated} updated"
        )
