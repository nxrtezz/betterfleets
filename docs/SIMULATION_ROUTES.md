# Simulation Routes Configuration

This document explains how to configure and add simulated vehicle routes to the live map.

## Overview

The simulation engine generates vehicle positions based on timetable data, allowing you to display vehicles on routes that don't have live GPS tracking. This is particularly useful for:

- Ferry services with long gaps between stops
- Routes with unreliable or no GPS data
- Testing and development purposes
- Displaying scheduled services when real-time data is unavailable

## Configuration

Simulation routes are configured in your Django settings file (`settings.py`) or a local settings override:

```python
SIMULATION_ROUTES = {
    "route-slug": {
        "service_id": 123,
        "vehicle_type": "ferry",
        "default_vehicle": {
            "id": -1,
            "reg": "SIM001",
            "name": "Simulated Ferry",
        },
    },
}
```

### Configuration Fields

Each route configuration requires:

- **`service_id`** (required, integer): The database ID of the service to simulate
- **`vehicle_type`** (optional, string): Type of vehicle (e.g., "ferry", "bus", "train")
- **`default_vehicle`** (optional, dict): Vehicle metadata for display
  - **`id`** (required): Vehicle ID (use negative numbers to distinguish from real vehicles)
  - **`reg`** (optional): Vehicle registration/identifier
  - **`name`** (optional): Vehicle display name

### Example Configurations

#### Ferry Service

```python
SIMULATION_ROUTES = {
    "solent-gosport-portsmouth": {
        "service_id": 12345,
        "vehicle_type": "ferry",
        "default_vehicle": {
            "id": -1,
            "reg": "SIM-FERRY",
            "name": "Simulated Ferry",
        },
    },
}
```

#### Bus Service

```python
SIMULATION_ROUTES = {
    "city-loop-service": {
        "service_id": 67890,
        "vehicle_type": "bus",
        "default_vehicle": {
            "id": -2,
            "reg": "SIM-BUS",
            "name": "Simulated Bus",
        },
    },
}
```

## How It Works

### Active Trip Detection

The simulation engine:

1. Loads timetable data for configured services
2. Checks which trips are currently active based on the current time
3. Handles overnight trips that cross midnight
4. Respects calendar rules (days of operation, holidays)

### Position Interpolation

For active trips, the engine:

1. Gets all stops in the trip sequence
2. Determines which segment the vehicle is currently on
3. Interpolates position between stops based on elapsed time
4. Calculates heading/bearing for the vehicle

For ferry-style routes with long gaps, direct interpolation is used between stops. This works well for point-to-point services.

### Vehicle Data Format

Simulated vehicles are returned in the same format as live vehicles from `/vehicles.json`, with additional metadata:

```json
{
  "id": "sim_12345_678",
  "coordinates": [-0.1, 51.5],
  "heading": 90,
  "datetime": "2024-01-15T10:30:00Z",
  "destination": "Portsmouth",
  "trip_id": 678,
  "service_id": 12345,
  "service": {
    "url": "/services/test-service",
    "line_name": "Test Service"
  },
  "operator": {
    "name": "Test Operator",
    "url": "/operators/test-operator"
  },
  "vehicle": {
    "id": -1,
    "name": "Simulated Ferry",
    "reg": "SIM-FERRY",
    "colour": "#ff6b6b",
    "css": "background: #ff6b6b;",
    "text_colour": "#fff"
  },
  "source": "simulation",
  "is_simulated": true
}
```

## Required Timetable Fields

For simulation to work correctly, the timetable must have:

- **Trip data**: Start and end times for each trip
- **Calendar data**: Days of operation and date ranges
- **Stop data**: At least two stops with coordinates
- **StopTime data**: Arrival/departure times for each stop

### Common Issues

#### Missing Stop Coordinates

If stops don't have location data, the simulation will skip that trip. Ensure all stops in the route have valid coordinates.

#### Invalid Time Ranges

If a stop's arrival time is before its departure time, interpolation will fail. Check timetable data for consistency.

#### Calendar Not Allowing Current Date

If the calendar doesn't allow the current date, no trips will be active. Verify calendar rules and date ranges.

## Validation

The simulation engine validates configuration on first load and logs any errors:

```python
from bustimes.simulation import validate_simulation_routes

errors = validate_simulation_routes()
for error in errors:
    print(error)
```

Common validation errors:

- Missing required `service_id`
- `service_id` is not an integer
- Invalid `default_vehicle` configuration

## Testing

To test simulation without affecting production:

1. Add test routes to a local settings file
2. Use the `/simulated-vehicles.json` endpoint to verify output
3. Check the map to ensure vehicles appear correctly

## API Endpoint

Simulated vehicles are available at:

```
GET /simulated-vehicles.json
```

This endpoint returns all currently active simulated vehicles in the same format as the live vehicle endpoint.

## Limitations

- Simulation is based on scheduled times, not real-time delays
- Position interpolation is linear between stops (not road-following)
- Vehicles disappear when their trip ends
- No support for real-time disruptions or diversions

## Future Enhancements

Potential improvements:

- Road-based routing for more realistic interpolation
- Support for real-time delays in simulation
- Multiple vehicles per service
- Custom vehicle liveries per route
- Simulation of dwell times at stops
