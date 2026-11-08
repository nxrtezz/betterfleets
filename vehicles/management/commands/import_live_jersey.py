from datetime import datetime

from django.contrib.gis.geos import Point
from django.db import IntegrityError
from django.utils.timezone import make_aware

from busstops.models import Service

from ...models import VehicleJourney, VehicleLocation
from ..import_live_vehicles import ImportLiveVehiclesCommand


class Command(ImportLiveVehiclesCommand):
    source_name = vehicle_code_scheme = "jersey"
    operator = "libertybus"
    url = "http://sojbuslivetimespublic.azurewebsites.net/api/Values?secondsAgo=360"

    @staticmethod
    def get_datetime(item):
        return datetime.fromisoformat(item["TimeOfUpdate"] + "Z")

    @staticmethod
    def get_vehicle_identity(item):
        return item["AssetRegistrationNumber"]

    @staticmethod
    def get_journey_identity(item):
        return (
            item["ServiceNumber"],
            item["OriginalStartTime"],
            item["Direction"],
        )

    @staticmethod
    def get_item_identity(item):
        return item["TimeOfUpdate"]

    def get_vehicle(self, item):
        vehicle_code = item["AssetRegistrationNumber"]
        defaults = {
            "operator_id": self.operator,
        }
        if vehicle_code[:1] == "J" and vehicle_code[1:].isdigit():
            defaults["reg"] = vehicle_code
        try:
            return self.vehicles.get_or_create(
                defaults, source=self.source, code=vehicle_code
            )
        except IntegrityError:
            # vehicle_operator_and_code is unique on (operator, code) but the
            # get_or_create lookup includes source - the vehicle may already
            # exist under a different source
            return (
                self.vehicles.get(
                    operator_id=self.operator, code__iexact=vehicle_code
                ),
                False,
            )

    def get_items(self):
        return super().get_items()["updates"]

    def get_journey(self, item, _):
        journey = VehicleJourney()
        journey.route_name = item["ServiceName"]
        journey.direction = item["Direction"]
        journey.datetime = make_aware(datetime.fromisoformat(item["OriginalStartTime"]))
        journey.service = Service.objects.filter(
            line_name=journey.route_name, operator=self.operator, current=True
        ).first()
        return journey

    def create_vehicle_location(self, item):
        return VehicleLocation(
            latlong=Point(item["Longitude"], item["Latitude"]), heading=item["Bearing"]
        )
