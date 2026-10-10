"""
Red Funnel (RF) Vehicle Tracking Importer

THIS ENDPOINT AND THESE INSTRUCTIONS ARE ONLY FOR THIS OPERATOR (Red Funnel, NOC: RF).
Do not reuse this code for other operators - each operator will have their own
dedicated container and transformation logic.

Endpoint: http://ais.redfunnel.co.uk/home/boats

Coordinate Transformation:
The Red Funnel API provides x,y coordinates in a custom map projection.
This script converts them to WGS84 lat/long using a linear transformation
derived from known reference points.

Reference points:
- x=807, y=132 → lat=50.894394558883086, lon=-1.4053852469929418 (Red Jet 7)
- x=900, y=708 → lat=50.759230392116166, lon=-1.2904174657707368 (East Cowes Terminal)

Data mapping:
- Vehicle ID: slug mapping (e.g., "JET7" → "RED7")
- Class to route:
  - "high-speed" → "RedJet"
  - "ferry" → "RedFunnel"
  - "out-of-service" → no route displayed
- Destination: second line of info array
- Heading: rotation value from marker
- Route number hidden when: info contains "At destination" or "Not in service"
- New trip/journey created when: route direction changes (Southampton ↔ Isle of Wight)
"""

import json
import logging
from datetime import timedelta
from time import sleep

import requests
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.db import IntegrityError
from django.utils import timezone
from redis.exceptions import ConnectionError

from busstops.models import DataSource, Operator, Service
from vehicles.models import Vehicle, VehicleJourney, VehicleLocation
from vehicles.utils import redis_client
from ..import_live_vehicles import ImportLiveVehiclesCommand

logger = logging.getLogger(__name__)

# Coordinate transformation constants for Red Funnel's custom projection
# Derived from reference points:
# - x=807, y=132 → lat=50.894394558883086, lon=-1.4053852469929418
# - x=900, y=708 → lat=50.759230392116166, lon=-1.2904174657707368
# LAT_SCALE = (lat2 - lat1) / (y2 - y1)
# LAT_OFFSET = lat1 - LAT_SCALE * y1
# LON_SCALE = (lon2 - lon1) / (x2 - x1)
# LON_OFFSET = lon1 - LON_SCALE * x1
LAT_SCALE = (50.759230392116166 - 50.894394558883086) / (708 - 132)
LAT_OFFSET = 50.894394558883086 - LAT_SCALE * 132
LON_SCALE = (-1.2904174657707368 - (-1.4053852469929418)) / (900 - 807)
LON_OFFSET = -1.4053852469929418 - LON_SCALE * 807


def redfunnel_to_latlong(x: float, y: float) -> tuple[float, float]:
    """
    Convert Red Funnel x,y coordinates to WGS84 lat/long.

    THIS TRANSFORMATION IS SPECIFIC TO RED FUNNEL ONLY.
    Do not use for other operators.

    Args:
        x: Red Funnel x coordinate
        y: Red Funnel y coordinate

    Returns:
        tuple of (latitude, longitude)
    """
    lat = LAT_SCALE * y + LAT_OFFSET
    lon = LON_SCALE * x + LON_OFFSET
    return lat, lon


def get_vehicle_slug(redfunnel_id: str) -> str:
    """
    Convert Red Funnel vehicle ID to fleet slug.

    THIS MAPPING IS SPECIFIC TO RED FUNNEL ONLY.

    Args:
        redfunnel_id: Red Funnel vehicle ID (e.g., "JET7", "FALC")

    Returns:
        Fleet slug (e.g., "RED7", "REDFAL")
    """
    # Mapping based on Red Funnel naming convention
    # JET7 → RED7, FALC → REDFAL, KEST → REDKES, EAGL → REDEAG, OSPR → REDOSP
    id_to_slug = {
        "JET7": "RED7",
        "FALC": "REDFAL",
        "KEST": "REDKES",
        "EAGL": "REDEAG",
        "OSPR": "REDOSP",
    }
    return id_to_slug.get(redfunnel_id, f"RED{redfunnel_id}")


def get_route_number(vehicle_class: str, info: list[str]) -> str | None:
    """
    Determine route number from vehicle class and status.

    THIS LOGIC IS SPECIFIC TO RED FUNNEL ONLY.

    Args:
        vehicle_class: "high-speed", "ferry", or "out-of-service"
        info: Info array from API (e.g., ["On route to", "Southampton"])

    Returns:
        Route number ("RedJet" or "RedFunnel") or None if not showing route
    """
    # Don't show route if at destination or not in service
    if len(info) >= 1 and info[0] in ["At destination", "Not in service"]:
        return None

    # Map class to route number
    if vehicle_class == "high-speed":
        return "RedJet"
    elif vehicle_class == "ferry":
        return "RedFunnel"
    elif vehicle_class == "out-of-service":
        return None

    return None


def get_destination(info: list[str]) -> str:
    """
    Extract destination from info array.

    THIS LOGIC IS SPECIFIC TO RED FUNNEL ONLY.

    Args:
        info: Info array from API (e.g., ["On route to", "Southampton"])

    Returns:
        Destination string (second line of info)
    """
    if len(info) >= 2:
        return info[1]
    return ""


def get_journey_identity(item: dict) -> tuple:
    """
    Generate journey identity for change detection.

    THIS LOGIC IS SPECIFIC TO RED FUNNEL ONLY.

    Args:
        item: Vehicle data from Red Funnel API

    Returns:
        Tuple for journey identity
    """
    vehicle_id = item.get("id")
    vehicle_class = item.get("class")
    info = item.get("label", {}).get("info", [])
    destination = get_destination(info)
    route_number = get_route_number(vehicle_class, info)

    return (vehicle_id, route_number, destination)


class Command(ImportLiveVehiclesCommand):
    source_name = "Red Funnel"
    vehicle_code_scheme = "RF"
    url = "http://ais.redfunnel.co.uk/home/boats"
    wait = 60

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "betterfleet/1.0"})
        self.journey_identities = {}
        self.operator = None

    def do_source(self):
        """Get or create the DataSource for Red Funnel."""
        self.source, _ = DataSource.objects.get_or_create(
            name=self.source_name,
            defaults={"url": self.url}
        )
        # Get the RF operator
        self.operator = Operator.objects.get(noc="RF")
        return self

    def get_vehicle(self, item: dict) -> tuple[Vehicle, bool]:
        """
        Get or create vehicle from Red Funnel data using find_or_merge_vehicle.

        THIS LOGIC IS SPECIFIC TO RED FUNNEL ONLY.

        Args:
            item: Vehicle data from Red Funnel API

        Returns:
            Tuple of (vehicle, created)
        """
        from vehicles.utils import find_or_merge_vehicle

        redfunnel_id = item.get("id")
        slug = get_vehicle_slug(redfunnel_id)

        # Use the same vehicle finding/creation logic as BODS
        vehicle = find_or_merge_vehicle(
            self.operator,
            redfunnel_id
        )

        if vehicle:
            return vehicle, False

        # Create new vehicle if not found
        vehicle = Vehicle(
            slug=slug,
            code=redfunnel_id,
            source=self.source,
            operator=self.operator,
        )
        vehicle.save()

        return vehicle, True

    def get_journey(self, item: dict, vehicle: Vehicle) -> VehicleJourney:
        """
        Get or create journey from Red Funnel data.

        THIS LOGIC IS SPECIFIC TO RED FUNNEL ONLY.

        Args:
            item: Vehicle data from Red Funnel API
            vehicle: Vehicle instance

        Returns:
            VehicleJourney instance
        """
        vehicle_class = item.get("class")
        info = item.get("label", {}).get("info", [])
        destination = get_destination(info)
        route_number = get_route_number(vehicle_class, info)

        journey = VehicleJourney(
            datetime=timezone.now(),
            destination=destination,
            route_name=route_number or "",
            source=self.source,
            vehicle=vehicle,
        )

        # Try to match service
        if route_number:
            service = Service.objects.filter(
                line_name__iexact=route_number,
                operator=self.operator,
                current=True
            ).first()
            if service:
                journey.service = service

        return journey

    def create_vehicle_location(self, item: dict) -> VehicleLocation | None:
        """
        Create VehicleLocation from Red Funnel data.

        THIS LOGIC IS SPECIFIC TO RED FUNNEL ONLY.

        Args:
            item: Vehicle data from Red Funnel API

        Returns:
            VehicleLocation instance or None
        """
        marker = item.get("marker", {})
        position = marker.get("position", {})
        x = position.get("x")
        y = position.get("y")
        rotation = marker.get("rotation")

        if x is None or y is None:
            return None

        # Convert Red Funnel x,y to lat/long
        lat, lon = redfunnel_to_latlong(x, y)

        return VehicleLocation(
            latlong=Point(lon, lat),
            heading=rotation if rotation is not None else None,
        )

    def handle_item(self, item: dict):
        """
        Handle a single vehicle item from Red Funnel API.

        THIS LOGIC IS SPECIFIC TO RED FUNNEL ONLY.

        Args:
            item: Vehicle data from Red Funnel API
        """
        try:
            vehicle, _ = self.get_vehicle(item)
        except Exception as e:
            logger.exception(f"Error getting vehicle: {e}")
            return

        location = self.create_vehicle_location(item)
        if not location:
            return

        journey = self.get_journey(item, vehicle)
        location.datetime = timezone.now()
        location.journey = journey

        # Save to database
        try:
            location.save()
        except IntegrityError:
            pass

        # Update vehicle
        vehicle.latest_journey = journey
        vehicle.save(update_fields=["latest_journey"])

        # Update Redis
        if redis_client:
            try:
                redis_json = location.get_redis_json()
                redis_json = json.dumps(redis_json, default=str)
                redis_client.set(f"vehicle{vehicle.id}", redis_json, ex=900)
                redis_client.geoadd(
                    "vehicle_location_locations",
                    (location.latlong.x, location.latlong.y, vehicle.id)
                )

                if journey.service_id:
                    redis_client.sadd(f"service{journey.service_id}vehicles", vehicle.id)
                    redis_client.expire(f"service{journey.service_id}vehicles", 600)

                if vehicle.operator_id:
                    redis_client.sadd(f"operator{vehicle.operator_id}vehicles", vehicle.id)
                    redis_client.expire(f"operator{vehicle.operator_id}vehicles", 600)
            except ConnectionError as e:
                logger.exception(f"Redis error: {e}")

    def update(self):
        """
        Main update loop for Red Funnel importer.

        THIS LOGIC IS SPECIFIC TO RED FUNNEL ONLY.
        """
        self.do_source()

        while True:
            try:
                logger.info(f"Fetching {self.url}")
                response = self.session.get(self.url, timeout=20)
                response.raise_for_status()
                items = response.json()

                logger.info(f"Processing {len(items)} vehicles")

                for item in items:
                    journey_identity = get_journey_identity(item)
                    vehicle_id = item.get("id")

                    # Check if journey has changed
                    if self.journey_identities.get(vehicle_id) != journey_identity:
                        self.handle_item(item)
                        self.journey_identities[vehicle_id] = journey_identity

                logger.info("Update complete")

            except Exception as e:
                logger.exception(f"Error during update: {e}")

            sleep(self.wait)

    def handle(self, *args, **options):
        """Run the importer."""
        logger.info("Starting Red Funnel vehicle importer")
        logger.info("THIS IMPORTER IS SPECIFIC TO RED FUNNEL (RF) ONLY")

        self.update()
