"""
Simulation engine for generating vehicle positions from timetable data.

This module provides functionality to simulate vehicle movement based on
timetable data, supporting routes with long gaps between stops (e.g., ferries).
"""

from datetime import datetime, timedelta, time, date
from typing import Optional, List, Dict, Any
from django.conf import settings
from django.utils import timezone
from django.contrib.gis.geos import Point
from django.db.models import Q
from django.core.cache import cache
import logging

from .models import Trip, StopTime, Route, Calendar, SimulationConfig
from busstops.models import Service

logger = logging.getLogger(__name__)


# Configuration for which routes to simulate (legacy support via settings)
# Can be overridden in Django settings via SIMULATION_ROUTES
SIMULATION_ROUTES = getattr(settings, 'SIMULATION_ROUTES', {})


def get_simulation_configs() -> Dict[str, Dict[str, Any]]:
    """
    Get all simulation configurations from database and settings.
    
    Returns a dictionary mapping service slugs to configuration dicts.
    """
    configs = {}
    
    # Load from database first
    try:
        db_configs = SimulationConfig.objects.filter(enabled=True).select_related('service')
        for config in db_configs:
            configs[config.service.slug] = {
                'service_id': config.service.id,
                'enabled': config.enabled,
                'vehicle_count': config.vehicle_count,
                'destination_inbound': config.destination_inbound,
                'destination_outbound': config.destination_outbound,
                'default_vehicles': config.get_vehicle_configs(),
                'source': 'database',
            }
    except Exception as e:
        logger.error("Error loading simulation configs from database: %s", e)
    
    # Merge with settings-based config (settings override database)
    for key, config in SIMULATION_ROUTES.items():
        configs[key] = {**config, 'source': 'settings'}
    
    return configs


def validate_simulation_routes() -> List[str]:
    """
    Validate simulation route configuration.
    
    Returns a list of validation errors. Empty list means all valid.
    
    Required fields for each route:
    - service_id: integer ID of the service to simulate
    - vehicle_type: string describing the vehicle type (optional)
    - default_vehicle: dict with vehicle metadata (optional)
      - id: vehicle ID (use negative for simulated)
      - reg: vehicle registration
      - name: vehicle name
    """
    errors = []
    
    for route_key, config in SIMULATION_ROUTES.items():
        if not isinstance(config, dict):
            errors.append(f"{route_key}: configuration must be a dictionary")
            continue
        
        if "service_id" not in config:
            errors.append(f"{route_key}: missing required field 'service_id'")
        elif not isinstance(config["service_id"], int):
            errors.append(f"{route_key}: 'service_id' must be an integer")
        
        if "default_vehicle" in config:
            vehicle = config["default_vehicle"]
            if not isinstance(vehicle, dict):
                errors.append(f"{route_key}: 'default_vehicle' must be a dictionary")
            else:
                if "id" not in vehicle:
                    errors.append(f"{route_key}: 'default_vehicle.id' is required")
                if "reg" not in vehicle and "name" not in vehicle:
                    errors.append(f"{route_key}: 'default_vehicle' must have 'reg' or 'name'")
    
    return errors


def get_active_trip_for_service(service_id: int, current_time: datetime) -> Optional[Trip]:
    """
    Find the active trip for a service at the current time.
    
    A trip is considered active if:
    - Its calendar allows the current date
    - The current time is between the trip's start and end times
    - The trip is the most recent one that has started but not yet ended
    
    Handles overnight trips by checking the previous day if current time is early.
    """
    current_date = current_time.date()
    current_time_of_day = current_time.time()
    
    # Check both current day and previous day for overnight trips
    dates_to_check = [current_date]
    if current_time_of_day.hour < 6:  # Early morning - check previous day for overnight trips
        dates_to_check.append(current_date - timedelta(days=1))
    
    for check_date in dates_to_check:
        # Get trips for this service that run on this date
        trips = Trip.objects.filter(
            route__service_id=service_id,
            calendar__start_date__lte=check_date,
        ).filter(
            Q(calendar__end_date__isnull=True) | Q(calendar__end_date__gte=check_date)
        ).select_related('calendar', 'route').prefetch_related('stoptime_set')
        
        active_trips = []
        for trip in trips:
            # Check if calendar allows this date
            if trip.calendar and not trip.calendar.allows(check_date):
                continue
                
            # Convert trip start/end times to datetime for comparison
            trip_start = trip.start_datetime(check_date)
            trip_end = trip.end_datetime(check_date)
            
            # Handle overnight trips that end on the next day
            if trip_end < trip_start:
                # Trip crosses midnight - check if current time is after start or before end
                if current_time >= trip_start or current_time <= trip_end:
                    active_trips.append((trip, trip_start, trip_end))
            else:
                # Normal trip - check if current time is within trip window
                if trip_start <= current_time <= trip_end:
                    active_trips.append((trip, trip_start, trip_end))
        
        if active_trips:
            # Return the trip that started most recently
            active_trips.sort(key=lambda x: x[1], reverse=True)
            return active_trips[0][0]
    
    return None


def interpolate_position(
    stop_a: StopTime,
    stop_b: StopTime,
    current_time: datetime,
    trip_date: date
) -> Optional[Point]:
    """
    Interpolate vehicle position between two stops based on time.
    
    For ferry-style routes, this performs direct interpolation between points.
    For road-based routes, you would typically use routing data, but this
    implementation uses direct interpolation for simplicity.
    
    Returns None if:
    - Stop coordinates are missing
    - Time duration is zero or invalid
    """
    if not stop_a.stop or not stop_b.stop:
        logger.debug("Missing stop coordinates for interpolation")
        return None
    
    # Check if stops have valid locations
    if not stop_a.stop.location or not stop_b.stop.location:
        logger.debug("Stop has no location data")
        return None
    
    # Get times
    time_a = stop_a.departure_datetime(trip_date)
    time_b = stop_b.arrival_datetime(trip_date)
    
    if time_a is None or time_b is None:
        logger.debug("Missing time data for stops")
        return None
    
    if time_a >= time_b:
        logger.debug("Invalid time range: start >= end")
        return None
    
    # Calculate progress ratio (0.0 to 1.0)
    total_duration = (time_b - time_a).total_seconds()
    elapsed = (current_time - time_a).total_seconds()
    
    if elapsed < 0:
        return Point(stop_a.stop.location.x, stop_a.stop.location.y)
    if elapsed >= total_duration:
        return Point(stop_b.stop.location.x, stop_b.stop.location.y)
    
    progress = elapsed / total_duration
    
    # Interpolate coordinates
    x = stop_a.stop.location.x + (stop_b.stop.location.x - stop_a.stop.location.x) * progress
    y = stop_a.stop.location.y + (stop_b.stop.location.y - stop_a.stop.location.y) * progress
    
    return Point(x, y)


def calculate_heading(point_a: Point, point_b: Point) -> float:
    """
    Calculate heading (bearing) between two points in degrees.
    """
    import math
    
    lat1 = math.radians(point_a.y)
    lat2 = math.radians(point_b.y)
    lon1 = math.radians(point_a.x)
    lon2 = math.radians(point_b.x)
    
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    
    bearing = math.atan2(x, y)
    bearing = math.degrees(bearing)
    bearing = (bearing + 360) % 360
    
    return bearing


def get_simulated_vehicle_position(
    service_id: int,
    current_time: Optional[datetime] = None
) -> Optional[Dict[str, Any]]:
    """
    Generate a simulated vehicle position for a service based on timetable data.
    
    Returns a dictionary compatible with the vehicle marker format, or None if
    no trip is currently active.
    """
    if current_time is None:
        current_time = timezone.now()
    
    trip = get_active_trip_for_service(service_id, current_time)
    if not trip:
        return None
    
    # Get stop times in sequence
    stop_times = list(trip.stoptime_set.filter(
        stop__isnull=False
    ).order_by('sequence', 'arrival', 'departure'))
    
    if len(stop_times) < 2:
        return None
    
    # Find which segment the vehicle is currently on
    trip_date = current_time.date()
    current_position = None
    current_heading = None
    prev_stop = None
    next_stop = None
    
    for i in range(len(stop_times) - 1):
        stop_a = stop_times[i]
        stop_b = stop_times[i + 1]
        
        time_a = stop_a.departure_datetime(trip_date)
        time_b = stop_b.arrival_datetime(trip_date)
        
        if time_a <= current_time <= time_b:
            # Vehicle is between these stops
            current_position = interpolate_position(stop_a, stop_b, current_time, trip_date)
            if current_position:
                current_heading = calculate_heading(stop_a.stop.location, stop_b.stop.location)
            prev_stop = stop_a.stop
            next_stop = stop_b.stop
            break
    
    # If not between stops, check if at a stop
    if current_position is None:
        for stop_time in stop_times:
            arrival = stop_time.arrival_datetime(trip_date)
            departure = stop_time.departure_datetime(trip_date)
            if arrival and departure and arrival <= current_time <= departure:
                current_position = stop_time.stop.location
                prev_stop = stop_time.stop
                # Try to get heading from next segment
                idx = stop_times.index(stop_time)
                if idx < len(stop_times) - 1:
                    next_st = stop_times[idx + 1]
                    if next_st.stop:
                        current_heading = calculate_heading(stop_time.stop.location, next_st.stop.location)
                break
    
    if not current_position:
        return None
    
    # Build vehicle data in the format expected by VehicleMarker
    route = trip.route
    service = route.service if route else None
    
    vehicle_data = {
        "id": f"sim_{service_id}_{trip.id}",
        "coordinates": [current_position.x, current_position.y],
        "heading": current_heading,
        "datetime": current_time.isoformat(),
        "destination": trip.destination.name if trip.destination else trip.headsign or "",
        "trip_id": trip.id,
        "service_id": service_id,
        "service": {
            "url": service.get_absolute_url() if service else "",
            "line_name": service.line_name if service else route.line_name or "",
        } if service else None,
        "operator": {
            "name": service.operator.name if service and service.operator else "",
            "url": service.operator.get_absolute_url() if service and service.operator else "",
        } if service and service.operator else None,
        "vehicle": {
            "id": -1,  # Negative ID indicates simulated
            "name": "Simulated Vehicle",
            "reg": "SIM",
            "colour": "#ff6b6b",  # Distinct color for simulated vehicles
            "css": "background: #ff6b6b;",
            "text_colour": "#fff",
        },
        "source": "simulation",
        "is_simulated": True,  # Marker to identify simulated vehicles
        "progress": {
            "id": trip.id,
            "sequence": stop_times.index(prev_stop) if prev_stop else 0,
            "prev_stop": prev_stop.name if prev_stop else "",
            "next_stop": next_stop.name if next_stop else "",
            "progress": 0.5,  # Simplified progress
        } if prev_stop else None,
    }
    
    return vehicle_data


def get_all_simulated_vehicles(current_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    Get simulated vehicles for all configured simulation routes.
    
    Returns a list of vehicle data dictionaries.
    Logs validation errors if configuration is invalid.
    """
    if current_time is None:
        current_time = timezone.now()
    
    # Validate configuration on first call
    if not hasattr(get_all_simulated_vehicles, '_validated'):
        errors = validate_simulation_routes()
        if errors:
            logger.warning("Simulation route configuration errors: %s", errors)
        get_all_simulated_vehicles._validated = True  # type: ignore
    
    vehicles = []
    
    # Get configurations from database and settings
    configs = get_simulation_configs()
    
    for service_slug, config in configs.items():
        service_id = config.get("service_id")
        if not service_id:
            logger.warning("Skipping %s: missing service_id", service_slug)
            continue
        
        # Skip if simulation is disabled
        if config.get("enabled", False) is False:
            continue
        
        try:
            # Get active trip for this service
            trip = get_active_trip_for_service(service_id, current_time)
            if not trip:
                continue
            
            # Generate vehicle for this trip
            vehicle = get_simulated_vehicle_position(service_id, current_time)
            if vehicle:
                # Apply destination names if configured
                if config.get("destination_inbound") and trip.inbound:
                    vehicle["destination"] = config["destination_inbound"]
                elif config.get("destination_outbound") and not trip.inbound:
                    vehicle["destination"] = config["destination_outbound"]
                
                # Apply vehicle configuration (support multiple vehicles)
                default_vehicles = config.get("default_vehicles", [])
                if default_vehicles:
                    # Create a vehicle for each configured vehicle
                    for i, vehicle_config in enumerate(default_vehicles):
                        vehicle_copy = vehicle.copy()
                        vehicle_copy["id"] = vehicle_config.get("id", -(i + 1))
                        vehicle_copy["vehicle"] = {
                            **vehicle["vehicle"],
                            **vehicle_config
                        }
                        vehicles.append(vehicle_copy)
                else:
                    # Single vehicle (legacy support)
                    if "default_vehicle" in config:
                        vehicle["vehicle"].update(config["default_vehicle"])
                    vehicles.append(vehicle)
        except Exception as e:
            logger.error("Error simulating vehicle for %s: %s", service_slug, e)
    
    return vehicles


def calculate_required_vehicles(service_id: int) -> Dict[str, Any]:
    """
    Calculate the number of vehicles required for a service based on timetable data.
    
    This analyzes overlapping trips to determine how many vehicles are needed
    to operate the service simultaneously.
    
    Returns a dictionary with:
    - required_vehicles: minimum number of vehicles needed
    - trips: list of trip details with start/end times
    - peak_times: times when maximum vehicles are needed
    """
    from django.utils import timezone
    
    current_date = timezone.now().date()
    
    # Get trips for this service that run today
    trips = Trip.objects.filter(
        route__service_id=service_id,
        calendar__start_date__lte=current_date,
    ).filter(
        Q(calendar__end_date__isnull=True) | Q(calendar__end_date__gte=current_date)
    ).select_related('calendar', 'route').prefetch_related('stoptime_set')
    
    # Filter to trips that run today
    active_trips = []
    for trip in trips:
        if trip.calendar and not trip.calendar.allows(current_date):
            continue
        
        trip_start = trip.start_datetime(current_date)
        trip_end = trip.end_datetime(current_date)
        
        active_trips.append({
            'id': trip.id,
            'start': trip_start,
            'end': trip_end,
            'inbound': trip.inbound,
            'headsign': trip.headsign or (trip.destination.name if trip.destination else ""),
        })
    
    if not active_trips:
        return {
            'required_vehicles': 0,
            'trips': [],
            'peak_times': [],
        }
    
    # Sort by start time
    active_trips.sort(key=lambda x: x['start'])
    
    # Calculate overlapping trips at each minute
    vehicle_usage = []
    for trip in active_trips:
        vehicle_usage.append({
            'start': trip['start'],
            'end': trip['end'],
            'type': 'start',
        })
        vehicle_usage.append({
            'start': trip['end'],
            'end': trip['end'],
            'type': 'end',
        })
    
    vehicle_usage.sort(key=lambda x: x['start'])
    
    # Track concurrent vehicles
    current_vehicles = 0
    max_vehicles = 0
    peak_periods = []
    current_peak_start = None
    
    for event in vehicle_usage:
        if event['type'] == 'start':
            current_vehicles += 1
            if current_vehicles > max_vehicles:
                max_vehicles = current_vehicles
                current_peak_start = event['start']
        else:
            if current_vehicles == max_vehicles and current_peak_start:
                peak_periods.append({
                    'start': current_peak_start,
                    'end': event['start'],
                    'vehicles': max_vehicles,
                })
                current_peak_start = None
            current_vehicles -= 1
    
    # Handle case where peak extends to end of day
    if current_peak_start:
        peak_periods.append({
            'start': current_peak_start,
            'end': active_trips[-1]['end'],
            'vehicles': max_vehicles,
        })
    
    return {
        'required_vehicles': max_vehicles,
        'trips': active_trips,
        'peak_times': peak_periods,
    }
