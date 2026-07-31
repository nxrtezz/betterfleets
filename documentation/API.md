# BetterFleet API Documentation

## Overview

The BetterFleet API provides RESTful endpoints for accessing public transport data including vehicles, operators, services, stops, and more. The API is built using Django REST Framework and follows standard REST conventions.

## Base URL

```
https://eeveeit.uk/api/
```

## Authentication

Currently, the API does not require authentication for read operations. All endpoints are publicly accessible.

## Available Endpoints

### Root Endpoint

```
GET /api/
```

Returns a list of all available API endpoints.

**Response:**
```json
{
    "vehicles": "https://eeveeit.uk/api/vehicles/",
    "liveries": "https://eeveeit.uk/api/liveries/",
    "vehicletypes": "https://eeveeit.uk/api/vehicletypes/",
    "operators": "https://eeveeit.uk/api/operators/",
    "services": "https://eeveeit.uk/api/services/"
}
```

---

## Vehicles

### List Vehicles

```
GET /api/vehicles/
```

Returns a paginated list of vehicles with filtering options.

**Query Parameters:**
- `limit`: Number of results to return (max 1000)
- `offset`: Number of results to skip
- Various filters available via VehicleFilter

**Response:**
```json
{
    "count": 1000,
    "next": "https://eeveeit.uk/api/vehicles/?limit=100&offset=100",
    "previous": null,
    "results": [
        {
            "id": 1,
            "external_id": "ABC123",
            "slug": "abc-123",
            "fleet_number": 123,
            "fleet_num": 123,
            "fleet_code": "ABC",
            "reg": "AB12 ABC",
            "registration": "AB12 ABC",
            "prev_registration": null,
            "previous_reg": null,
            "vehicle_type": {
                "id": 1,
                "vehicle_id": 1,
                "external_id": "VT001",
                "name": "Alexander Dennis Enviro400",
                "style": "double decker",
                "type": "double decker",
                "fuel": "diesel",
                "company": "Alexander Dennis",
                "double_decker": true,
                "coach": false,
                "electric": false
            },
            "livery": {
                "id": 1,
                "livery_id": 1,
                "name": "Stagecoach Blue",
                "left": "#0033CC",
                "right": "#0033CC"
            },
            "branding": null,
            "operator": {
                "id": 1,
                "slug": "stagecoach",
                "name": "Stagecoach"
            },
            "garage": {
                "id": 1,
                "code": "SCG",
                "name": "Stagecoach Garage"
            },
            "name": null,
            "notes": null,
            "withdrawn": false,
            "special_features": ["WiFi", "USB Charging"]
        }
    ]
}
```

### Get Specific Vehicle

```
GET /api/vehicles/{id}/
```

Returns detailed information about a specific vehicle.

---

## Liveries

### List Liveries

```
GET /api/liveries/
```

Returns a list of vehicle liveries with filtering options.

**Response:**
```json
{
    "count": 50,
    "next": null,
    "previous": null,
    "results": [
        {
            "id": 1,
            "livery_id": 1,
            "external_id": "LIV001",
            "name": "Stagecoach Blue",
            "css": "background-color: #0033CC;",
            "left_css": "background-color: #0033CC;",
            "right_css": "background-color: #0033CC;",
            "white_text": true,
            "text_colour": "#FFFFFF",
            "stroke_colour": "#000000"
        }
    ]
}
```

---

## Vehicle Types

### List Vehicle Types

```
GET /api/vehicletypes/
```

Returns a list of vehicle types with filtering options.

**Response:**
```json
{
    "count": 30,
    "next": null,
    "previous": null,
    "results": [
        {
            "id": 1,
            "vehicle_id": 1,
            "external_id": "VT001",
            "name": "Alexander Dennis Enviro400",
            "style": "double decker",
            "type": "double decker",
            "fuel": "diesel",
            "company": "Alexander Dennis",
            "double_decker": true,
            "coach": false,
            "electric": false
        }
    ]
}
```

---

## Operators

### List Operators

```
GET /api/operators/
```

Returns a paginated list of operators with filtering options. Includes associated garages.

**Query Parameters:**
- Cursor-based pagination
- Various filters available via OperatorFilter

**Response:**
```json
{
    "count": 100,
    "next": "https://eeveeit.uk/api/operators/?cursor=...",
    "previous": null,
    "results": [
        {
            "noc": "SCCB",
            "external_id": "OP001",
            "slug": "stagecoach",
            "name": "Stagecoach",
            "slogan": "Good value, simple fares",
            "logo": "https://example.com/logo.png",
            "aka": null,
            "preserved": false,
            "ceased_operations_on": null,
            "vehicle_mode": "bus",
            "mode": "bus",
            "region_id": "GB",
            "url": "https://www.stagecoach.com",
            "twitter": "stagecoachbus",
            "social_x": "stagecoachbus",
            "social_fb": "stagecoachbus",
            "social_instagram": "stagecoachbus",
            "social_linkedin": null,
            "social_youtube": null,
            "social_tiktok": null,
            "social_threads": null,
            "social_bluesky": null,
            "social_mastodon": null,
            "social_other": null,
            "garages": [
                {
                    "garage_id": 1,
                    "external_id": "GAR001",
                    "code": "SCG",
                    "name": "Stagecoach Garage",
                    "owner": "SCCB",
                    "region_id": "GB"
                }
            ]
        }
    ]
}
```

### Get Specific Operator

```
GET /api/operators/{noc}/
```

Returns detailed information about a specific operator including their garages.

---

## Services

### List Services

```
GET /api/services/
```

Returns a list of current services with filtering options.

**Query Parameters:**
- Various filters available via ServiceFilter

**Response:**
```json
{
    "count": 500,
    "next": null,
    "previous": null,
    "results": [
        {
            "id": 1,
            "slug": "stagecoach-1",
            "service_code": "SC001",
            "line_name": "1",
            "line_brand": "City 1",
            "description": "City Centre to Railway Station",
            "region_id": "GB",
            "mode": "bus",
            "operator": [
                {
                    "id": 1,
                    "noc": "SCCB",
                    "slug": "stagecoach",
                    "name": "Stagecoach"
                }
            ],
            "current": true,
            "tracking": true,
            "public_use": true,
            "is_rail_replacement": false,
            "train_operator": null,
            "modified_at": "2024-01-15T10:30:00Z"
        }
    ]
}
```

### Get Specific Service

```
GET /api/services/{id}/
```

Returns detailed information about a specific service.

---

## Stops

### List Stops

```
GET /api/stops/
```

Returns a paginated list of stops with filtering options.

**Query Parameters:**
- Cursor-based pagination
- Various filters available via StopFilter

**Response:**
```json
{
    "count": 10000,
    "next": "https://eeveeit.uk/api/stops/?cursor=...",
    "previous": null,
    "results": [
        {
            "atco_code": "01000012345",
            "naptan_code": "12345",
            "common_name": "Market Street",
            "name": "Market Street",
            "long_name": "Market Street (Stop A)",
            "location": [-1.1234, 52.5678],
            "indicator": "Stop A",
            "icon": "bus",
            "line_names": ["1", "2", "3"],
            "bearing": 45,
            "heading": "NE",
            "stop_type": "BCT",
            "bus_stop_type": "MKD",
            "created_at": "2020-01-01T00:00:00Z",
            "modified_at": "2024-01-15T10:30:00Z",
            "active": true
        }
    ]
}
```

---

## Trips

### List Trips

```
GET /api/trips/
```

Returns a paginated list of trips with filtering options.

**Query Parameters:**
- Cursor-based pagination
- Various filters available via TripFilter

**Response:**
```json
{
    "count": 1000,
    "next": "https://eeveeit.uk/api/trips/?cursor=...",
    "previous": null,
    "results": [
        {
            "id": 1,
            "vehicle_journey_code": "VJ001",
            "ticket_machine_code": "TMC001",
            "block": "B1",
            "start": "2024-01-15T06:00:00Z",
            "end": "2024-01-15T08:00:00Z",
            "headsign": "Railway Station",
            "service": {
                "id": 1,
                "line_name": "1",
                "slug": "stagecoach-1",
                "mode": "bus"
            },
            "operator": {
                "noc": "SCCB",
                "name": "Stagecoach",
                "vehicle_mode": "bus",
                "slug": "stagecoach"
            },
            "notes": [],
            "times": [...]
        }
    ]
}
```

### Get Specific Trip

```
GET /api/trips/{id}/
```

Returns detailed information about a specific trip including stop times.

---

## Vehicle Journeys

### List Vehicle Journeys

```
GET /api/vehiclejourneys/
```

Returns a paginated list of vehicle journeys with filtering options.

**Query Parameters:**
- Cursor-based pagination (smaller page size: 10)
- Various filters available via VehicleJourneyFilter

**Response:**
```json
{
    "count": 5000,
    "next": "https://eeveeit.uk/api/vehiclejourneys/?cursor=...",
    "previous": null,
    "results": [
        {
            "id": 1,
            "datetime": "2024-01-15T06:30:00Z",
            "vehicle": {
                "id": 1,
                "slug": "abc-123",
                "fleet_code": "ABC",
                "reg": "AB12 ABC"
            },
            "route_name": "1",
            "destination": "Railway Station",
            "trip_id": 1
        }
    ]
}
```

### Get Specific Vehicle Journey

```
GET /api/vehiclejourneys/{id}/
```

Returns detailed information about a specific vehicle journey including time-aware polyline data.

**Additional Response Fields:**
- `times`: Detailed stop times for the journey
- `time_aware_polyline`: Encoded polyline with time information
- `service`: Basic service information

---

## Filtering

All endpoints support filtering through Django Filter Backend. Specific filters vary by endpoint:

### Vehicle Filters
- `operator`: Filter by operator ID
- `vehicle_type`: Filter by vehicle type ID
- `livery`: Filter by livery ID
- `garage`: Filter by garage ID
- `fleet_number`: Filter by fleet number
- `reg`: Filter by registration

### Operator Filters
- `region`: Filter by region ID
- `vehicle_mode`: Filter by vehicle mode (bus, coach, tram, etc.)

### Service Filters
- `operator`: Filter by operator ID
- `mode`: Filter by service mode
- `region`: Filter by region ID
- `current`: Filter by current status

### Stop Filters
- `atco_code`: Filter by ATCO code
- `naptan_code`: Filter by NaPTAN code
- `region`: Filter by region ID

---

## Pagination

Different endpoints use different pagination strategies:

### Limit-Offset Pagination
Used for: `vehicles`, `liveries`, `vehicletypes`
- `limit`: Maximum number of results (max 1000)
- `offset`: Number of results to skip

### Cursor Pagination
Used for: `operators`, `stops`, `trips`
- Provides `next` and `previous` cursor URLs
- More efficient for large datasets
- Page size: 100 (operators, stops), 10 (trips)

---

## Data Models

### Vehicle
Represents a physical vehicle in the fleet with details about type, livery, operator, and garage assignment.

### Operator
Represents a transport operator with contact details, social media links, and associated garages.

### Service
Represents a public transport service (route) with line information, operators, and tracking status.

### Stop
Represents a physical stop or station with location, naming, and service line information.

### Trip
Represents a scheduled journey with timing information and service details.

### Garage
Represents an operator's garage/depot with location and contact information.

---

## Error Responses

The API uses standard HTTP status codes:

- `200 OK`: Successful request
- `400 Bad Request`: Invalid request parameters
- `404 Not Found`: Resource not found
- `500 Internal Server Error`: Server error

**Error Response Format:**
```json
{
    "detail": "Error message describing what went wrong"
}
```

---

## Rate Limiting

Currently, there are no rate limits imposed on the API. However, clients should implement reasonable rate limiting and caching to avoid overloading the server.

---

## Caching

Clients are encouraged to cache API responses. The `modified_at` field is provided on most resources to help with cache invalidation.

---

## Best Practices

1. **Use filtering**: Always use the most specific filters possible to reduce response size
2. **Pagination**: Always follow pagination links rather than manipulating offset/limit manually
3. **Caching**: Implement client-side caching using `modified_at` timestamps
4. **Error handling**: Implement proper error handling for all API calls
5. **User-Agent**: Include a descriptive User-Agent header in requests

---

## Future Enhancements

Potential future additions to the API:
- Real-time vehicle tracking data
- Historical journey data
- Fare information
- Disruption and service alerts
- Advanced filtering and search capabilities
