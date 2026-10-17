from django.core.management.base import BaseCommand
from tqdm import tqdm

from busstops.bustimes_sync import BustimesApiClient, compact_text, compact_registration
from busstops.models import Operator
from vehicles.models import Vehicle, VehicleType, Livery


class Command(BaseCommand):
    help = "Import all vehicles from bustimes.org/api/vehicle - field by field"

    def handle(self, *args, **options):
        client = BustimesApiClient()
        self.stdout.write("Importing vehicles from bustimes.org/api/vehicle...")

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
                # Get external_id
                external_id = compact_text(item.get("id")) or None

                # Get operator
                operator_noc = compact_text(item.get("operator"))
                operator = None
                if operator_noc:
                    operator = Operator.objects.filter(noc=operator_noc).first()

                # Get vehicle type
                vehicle_type_name = compact_text(item.get("vehicle_type") or item.get("type"))
                vehicle_type = None
                if vehicle_type_name:
                    vehicle_type = VehicleType.objects.filter(name__iexact=vehicle_type_name).first()

                # Get livery
                livery_name = compact_text(item.get("livery"))
                livery = None
                if livery_name:
                    livery = Livery.objects.filter(name__iexact=livery_name).first()

                # Get code
                code = compact_text(item.get("code"))
                if not code:
                    code = external_id or "unknown"

                # Try to find existing vehicle by external_id or code+operator
                vehicle = None
                if external_id:
                    vehicle = Vehicle.objects.filter(external_id=external_id).first()
                if not vehicle and operator and code:
                    vehicle = Vehicle.objects.filter(operator=operator, code=code).first()

                # Get ALL fields from the API item
                fleet_code = compact_text(item.get("fleet_code") or item.get("fleet_number"))
                reg = compact_registration(item.get("reg") or item.get("registration"))
                prev_registration = compact_registration(item.get("prev_registration") or item.get("previous_reg"))
                name = compact_text(item.get("name"))
                branding = compact_text(item.get("branding"))
                notes = compact_text(item.get("notes"))
                colours = compact_text(item.get("colours"))
                withdrawn = bool(item.get("withdrawn", False))
                preserved = bool(item.get("preserved", False))
                fleet_support_vehicle = bool(item.get("fleet_support_vehicle", False))
                vor = bool(item.get("vor", False))
                awaiting_delivery = bool(item.get("awaiting_delivery", False))
                trainer_vehicle = bool(item.get("trainer_vehicle", False))
                demonstrator = bool(item.get("demonstrator", False))
                slug = compact_text(item.get("slug"))

                # Build values dict
                values = {
                    "code": code,
                    "fleet_code": fleet_code,
                    "reg": reg,
                    "prev_registration": prev_registration,
                    "name": name,
                    "branding": branding,
                    "notes": notes,
                    "colours": colours,
                    "withdrawn": withdrawn,
                    "preserved": preserved,
                    "fleet_support_vehicle": fleet_support_vehicle,
                    "vor": vor,
                    "awaiting_delivery": awaiting_delivery,
                    "trainer_vehicle": trainer_vehicle,
                    "demonstrator": demonstrator,
                }

                if operator:
                    values["operator"] = operator
                if vehicle_type:
                    values["vehicle_type"] = vehicle_type
                if livery:
                    values["livery"] = livery
                if external_id:
                    values["external_id"] = external_id
                if slug:
                    values["slug"] = slug

                if fleet_code and fleet_code.isdigit():
                    values["fleet_number"] = int(fleet_code)

                if vehicle:
                    # Update ALL fields
                    for field, value in values.items():
                        if value is not None:
                            setattr(vehicle, field, value)
                    vehicle.save()
                    updated += 1
                else:
                    # Create new vehicle with ALL fields
                    vehicle = Vehicle.objects.create(**values)
                    created += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing vehicle: {e}"))
                continue

        self.stdout.write(
            f"Vehicles import complete: {created} created, {updated} updated"
        )
