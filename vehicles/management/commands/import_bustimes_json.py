import re
from ciso8601 import parse_datetime
from django.contrib.gis.geos import Point
from django.utils import timezone

from busstops.models import DataSource, Operator, Service
from ...models import Vehicle, VehicleJourney, VehicleLocation
from ..import_live_vehicles import ImportLiveVehiclesCommand


class Command(ImportLiveVehiclesCommand):
    source_name = vehicle_code_scheme = "bustimes.org"
    wait = 60

    def do_source(self):
        self.source, _ = DataSource.objects.get_or_create(
            name=self.source_name,
            defaults={"url": "https://bustimes.org/vehicles.json"}
        )
        return self

    def get_items(self):
        # Build URL with bounding box parameters if provided
        url = self.url
        if hasattr(self, 'ymax') and self.ymax:
            params = []
            for param in ['ymax', 'xmax', 'ymin', 'xmin']:
                if hasattr(self, param):
                    params.append(f"{param}={getattr(self, param)}")
            if params:
                url = f"{url}?{'&'.join(params)}"
        self.url = url
        return super().get_items()

    @staticmethod
    def add_arguments(parser):
        parser.add_argument("--ymax", type=float, help="Maximum latitude")
        parser.add_argument("--xmax", type=float, help="Maximum longitude")
        parser.add_argument("--ymin", type=float, help="Minimum latitude")
        parser.add_argument("--xmin", type=float, help="Minimum longitude")
        ImportLiveVehiclesCommand.add_arguments(parser)

    @staticmethod
    def get_vehicle_identity(item):
        # Extract vehicle identity from the vehicle URL
        # e.g., "/vehicles/wdbc-sq-1629" -> "1629"
        vehicle_url = item.get("vehicle", {}).get("url", "")
        match = re.search(r'/vehicles/[^/]+-(\d+)', vehicle_url)
        if match:
            return match.group(1)
        # Fallback: try to extract from name
        name = item.get("vehicle", {}).get("name", "")
        match = re.search(r'(\d+)', name)
        if match:
            return match.group(1)
        return ""

    @staticmethod
    def get_journey_identity(item):
        return (
            item.get("trip_id"),
            item.get("datetime"),
            item.get("destination"),
        )

    @staticmethod
    def get_item_identity(item):
        return item.get("id")

    @staticmethod
    def get_datetime(item):
        datetime_str = item.get("datetime")
        if datetime_str:
            return parse_datetime(datetime_str)
        return None

    def get_vehicle(self, item):
        vehicle_identity = self.get_vehicle_identity(item)
        if not vehicle_identity:
            return None, False

        # Try to find vehicle by code (fleet number)
        vehicles = Vehicle.objects.filter(code__iexact=vehicle_identity)
        
        # If multiple vehicles, try to match by registration from name
        if vehicles.count() > 1:
            name = item.get("vehicle", {}).get("name", "")
            reg_match = re.search(r'[A-Z]{1,2}\d{2}[A-Z]{3}', name.upper())
            if reg_match:
                reg = reg_match.group(0)
                vehicles = vehicles.filter(reg__iexact=reg)
        
        if vehicles.exists():
            return vehicles.first(), False
        
        # Create new vehicle if not found
        # Try to extract registration from name
        name = item.get("vehicle", {}).get("name", "")
        reg_match = re.search(r'[A-Z]{1,2}\d{2}[A-Z]{3}', name.upper())
        reg = reg_match.group(0) if reg_match else None
        
        vehicle = Vehicle(
            code=vehicle_identity,
            reg=reg,
            source=self.source,
        )
        vehicle.save()
        return vehicle, True

    def get_service(self, item):
        line_name = item.get("service", {}).get("line_name")
        if not line_name:
            return None
        
        services = Service.objects.filter(
            line_name__iexact=line_name,
            current=True
        )
        
        if services.exists():
            return services.first()
        return None

    def get_journey(self, item, vehicle):
        datetime = self.get_datetime(item)
        trip_id = item.get("trip_id")
        destination = item.get("destination", "")
        line_name = item.get("service", {}).get("line_name", "")
        
        latest_journey = vehicle.latest_journey
        
        # Check if this is the same journey
        if latest_journey and latest_journey.datetime == datetime:
            return latest_journey
        
        # Check if journey already exists
        if datetime:
            existing_journey = vehicle.vehiclejourney_set.filter(
                datetime=datetime
            ).first()
            if existing_journey:
                return existing_journey
        
        # Create new journey
        journey = VehicleJourney(
            datetime=datetime,
            destination=destination,
            route_name=line_name,
            code=str(trip_id) if trip_id else "",
            source=self.source,
        )
        
        # Try to match service
        service = self.get_service(item)
        if service:
            journey.service = service
            
            # Try to match trip
            if datetime and not journey.id:
                journey.trip = journey.get_trip(
                    departure_time=datetime,
                    destination=destination
                )
        
        return journey

    def create_vehicle_location(self, item):
        coordinates = item.get("coordinates")
        if not coordinates or len(coordinates) != 2:
            return None
        
        heading = item.get("heading")
        if heading is not None:
            try:
                heading = float(heading)
                if heading == -1:
                    heading = None
            except (ValueError, TypeError):
                heading = None
        
        return VehicleLocation(
            latlong=Point(coordinates[0], coordinates[1]),
            heading=heading,
        )
