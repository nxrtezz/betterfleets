from django.db import transaction
from django.utils import timezone

from busstops.bustimes_sync import apply_sync_fields, compact_registration, compact_text
from bustimes.models import Trip
from vehicles.models import Vehicle, VehicleCode, VehicleJourney

from ._sync_bustimes import (
    BUSTIMES_SCHEME,
    BustimesSyncCommand,
    api_id,
    parse_api_datetime,
    resolve_service_for_journey,
    resolve_vehicle,
)


class Command(BustimesSyncCommand):
    help = "Sync vehicle journeys from the Bustimes API."
    endpoint = "vehiclejourneys/"

    def get_or_create_vehicle(self, item):
        vehicle = resolve_vehicle(item)
        vehicle_data = item.get("vehicle") or {}
        if vehicle or not vehicle_data:
            return vehicle

        reg = compact_registration(vehicle_data.get("reg"))
        code = compact_text(
            vehicle_data.get("fleet_code")
            or vehicle_data.get("slug")
            or vehicle_data.get("id")
            or reg
        )
        if not code:
            return None

        vehicle = Vehicle(code=code, reg=reg)
        vehicle.save()
        if vehicle_data.get("id"):
            VehicleCode.objects.get_or_create(
                scheme=BUSTIMES_SCHEME,
                code=str(vehicle_data["id"]),
                defaults={"vehicle": vehicle},
            )
        return vehicle

    @transaction.atomic
    def sync_item(self, item, options):
        source = self.get_source()
        external_id = api_id(item)
        journey = VehicleJourney.objects.filter(source=source, code=external_id).first()
        if journey is None:
            journey = VehicleJourney(source=source, code=external_id)

        when = parse_api_datetime(item.get("datetime"))
        if when is None:
            return False, False, 1

        vehicle = self.get_or_create_vehicle(item)
        trip = None
        if item.get("trip_id"):
            trip = Trip.objects.filter(pk=item["trip_id"]).first()
        service = resolve_service_for_journey(item, vehicle, trip)

        values = {
            "source": source,
            "code": external_id,
            "datetime": when,
            "date": timezone.localdate(when),
            "vehicle": vehicle,
            "route_name": compact_text(item.get("route_name")),
            "destination": compact_text(item.get("destination")),
            "trip": trip,
            "service": service,
        }
        result = apply_sync_fields(
            instance=journey,
            object_type="vehiclejourney",
            external_id=external_id,
            values=values,
            payload=item,
            dry_run=options["dry_run"],
            force=options["force"],
        )

        if not options["dry_run"] and vehicle and journey.pk:
            if not vehicle.latest_journey or vehicle.latest_journey.datetime <= journey.datetime:
                vehicle.latest_journey = journey
                vehicle.save(update_fields=["latest_journey"])

        return result.created, result.updated, len(result.skipped_fields)

    def handle(self, *args, **options):
        created = updated = skipped = 0
        progress = self.progress(options)
        for item in self.iter_items_with_progress(options, progress):
            item_created, item_updated, item_skipped = self.sync_item(item, options)
            created += int(item_created)
            updated += int(item_updated)
            skipped += item_skipped
            progress.tick(created=item_created, updated=item_updated, skipped=item_skipped)
        self.print_summary(created, updated, skipped)
