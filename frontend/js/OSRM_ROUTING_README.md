# OSRM Routing with Interactive Waypoint Placement

This implementation provides OSRM routing support with ordered waypoints and interactive waypoint placement for the BetterFleet project.

## Overview

The OSRM routing implementation consists of three main files:

1. **`osrmRouting.ts`** - Core routing utility with waypoint support
2. **`OSRMRouteMap.tsx`** - React component for displaying OSRM routes on a map
3. **`RouteEditorWithWaypoints.tsx`** - Interactive route editor with waypoint creation

## Key Features

- **Ordered Route Points**: OSRM visits points in strict order (Stop A → Waypoint 1 → Waypoint 2 → Stop B → ...)
- **Interactive Waypoint Placement**: Click anywhere on the map to create waypoints
- **Stop Selection**: Click on existing stops to add them to the route
- **Distinct Visual Styles**: Stops and waypoints use different marker styles in editor mode
- **Hidden Waypoints on Public Maps**: Waypoints are routing hints only and are NOT rendered on public-facing maps
- **Editable Waypoints**: Waypoints can be moved, removed, and reordered in the editor
- **TypeScript Support**: Full type definitions for route configurations and responses

## Data Structures

### RoutePoint
```typescript
type RoutePoint = {
  type: "stop" | "waypoint";  // Distinguishes stops from waypoints
  lat: number;
  lng: number;
  stopId?: number;  // Only present for stops
};
```

### RouteConfig
```typescript
type RouteConfig = {
  routePoints: RoutePoint[];  // Ordered list of stops and waypoints
};
```

## Usage Example

### Public-Facing Map (Waypoints Hidden)

```typescript
import OSRMRouteMap from "./OSRMRouteMap";

<OSRMRouteMap
  route={{
    routePoints: [
      { type: "stop", lat: 51.5074, lng: -0.1278, stopId: 1 },      // London
      { type: "waypoint", lat: 51.4700, lng: -0.4543 },             // Hidden routing guide
      { type: "waypoint", lat: 51.3811, lng: -2.3590 },             // Hidden routing guide
      { type: "stop", lat: 51.4545, lng: -2.5879, stopId: 2 },     // Bristol
    ],
  }}
  osrmUrl="http://localhost:5000"
  showWaypoints={false} // Hide waypoints on public maps
/>
```

### Editor Map (Waypoints Visible)

```typescript
import OSRMRouteMap from "./OSRMRouteMap";

<OSRMRouteMap
  route={{
    routePoints: [
      { type: "stop", lat: 51.5074, lng: -0.1278, stopId: 1 },
      { type: "waypoint", lat: 51.4700, lng: -0.4543 },
      { type: "waypoint", lat: 51.3811, lng: -2.3590 },
      { type: "stop", lat: 51.4545, lng: -2.5879, stopId: 2 },
    ],
  }}
  osrmUrl="http://localhost:5000"
  showWaypoints={true} // Show waypoints in editor mode
/>
```

### Interactive Route Editor

```typescript
import RouteEditorWithWaypoints from "./RouteEditorWithWaypoints";

<RouteEditorWithWaypoints
  initialRoutePoints={[
    { type: "stop", lat: 51.5074, lng: -0.1278, stopId: 1 },
    { type: "stop", lat: 51.4545, lng: -2.5879, stopId: 2 },
  ]}
  stops={stopsGeoJson}
  onSave={(routePoints) => {
    // Save route points to backend
    console.log("Saving route:", routePoints);
  }}
/>
```

### Expected OSRM Coordinate Sequence

For the example above, the OSRM request will be:

```
GET /route/v1/driving/-0.1278,51.5074;-0.4543,51.4700;-2.3590,51.3811;-2.5879,51.4545?overview=full&geometries=geojson
```

The coordinates are ordered as:
1. Stop (London)
2. Waypoint near Heathrow
3. Waypoint near Bath
4. Stop (Bristol)

### Expected Rendered Map

**Public-Facing Map (showWaypoints=false):**
- **Markers**: Only London and Bristol stops are visible
- **No Waypoint Markers**: Heathrow and Bath waypoints are invisible
- **Route Polyline**: The route bends through the hidden waypoints in order

**Editor Map (showWaypoints=true):**
- **Markers**: All stops (red) and waypoints (blue) are visible
- **Different Styles**: Stops use larger red circles, waypoints use smaller blue circles
- **Route Polyline**: The route bends through all points in order

## API Reference

### `fetchOSRMRoute(config, osrmUrl?)`

Fetches a route from the OSRM server with waypoint support.

**Parameters:**
- `config`: RouteConfig - Route configuration with ordered list of route points
- `osrmUrl`: string (optional) - Custom OSRM server URL (defaults to `http://localhost:5000` or `process.env.OSRM_SERVER_URL`)

**Returns:** Promise<OSRMRouteResponse>

**Example:**
```typescript
import { fetchOSRMRoute, extractRouteGeometry } from "./osrmRouting";

const response = await fetchOSRMRoute({
  routePoints: [
    { type: "stop", lat: 51.5074, lng: -0.1278, stopId: 1 },
    { type: "waypoint", lat: 51.4700, lng: -0.4543 },
    { type: "stop", lat: 51.4545, lng: -2.5879, stopId: 2 },
  ],
});

const geometry = extractRouteGeometry(response);
```

### `fetchOSRMRouteFromStops(route, osrmUrl?)`

Fetches a route from OSRM server using stops in exact database order.

This function follows the exact order of stops as stored in the route. It does NOT sort, optimize, or reorder stops in any way. Uses OSRM Route Service (`/route/v1`) only - never Trip Service.

**Parameters:**
- `route`: RouteWithStops - Route with stops in database order (each stop has `longitude`, `latitude`, and `name` properties)
- `osrmUrl`: string (optional) - Custom OSRM server URL (defaults to `http://localhost:5000` or `process.env.OSRM_SERVER_URL`)

**Returns:** Promise<OSRMRouteResponse>

**Example:**
```typescript
import { fetchOSRMRouteFromStops, extractRouteGeometry } from "./osrmRouting";

const response = await fetchOSRMRouteFromStops({
  stops: [
    { longitude: -0.1278, latitude: 51.5074, name: "Eastbourne Station" },
    { longitude: -0.4543, latitude: 51.4700, name: "Terminus Road" },
    { longitude: -2.3590, latitude: 51.3811, name: "Seaside" },
    { longitude: -2.5879, latitude: 51.4545, name: "Sovereign Harbour" },
  ],
});

const geometry = extractRouteGeometry(response);
```

**Important Notes:**
- This function logs the stop names to the console for verification
- Coordinates are passed to OSRM in the exact order they appear in the database/UI
- The first stop is the first coordinate, the second stop is the second coordinate, etc.
- No sorting, optimization, or reordering is performed

### `migrateLegacyRouteConfig(legacyConfig)`

Migrates a legacy route configuration (with origin/destination/waypoints) to the new format (with ordered route points).

**Parameters:**
- `legacyConfig`: LegacyRouteConfig - Legacy route configuration

**Returns:** RouteConfig - New route configuration with ordered route points

**Example:**
```typescript
import { migrateLegacyRouteConfig } from "./osrmRouting";

const legacyConfig = {
  origin: { lat: 51.5074, lng: -0.1278, stopId: 1 },
  destination: { lat: 51.4545, lng: -2.5879, stopId: 2 },
  waypoints: [
    { lat: 51.4700, lng: -0.4543 },
  ],
};

const newConfig = migrateLegacyRouteConfig(legacyConfig);
// Result: { routePoints: [stop, waypoint, stop] }
```

### `extractRouteGeometry(response)`

Extracts the route geometry from an OSRM response.

**Parameters:**
- `response`: OSRMRouteResponse - OSRM route response

**Returns:** GeoJSON.LineString | null

### `getRouteDistance(response)`

Gets the route distance in meters from an OSRM response.

**Parameters:**
- `response`: OSRMRouteResponse - OSRM route response

**Returns:** number | null

### `getRouteDuration(response)`

Gets the route duration in seconds from an OSRM response.

**Parameters:**
- `response`: OSRMRouteResponse - OSRM route response

**Returns:** number | null

## OSRM Server Setup

To use this implementation, you need an OSRM server running. You can:

1. **Use a local OSRM instance:**
   ```bash
   # Download map data (e.g., for UK)
   wget https://download.geofabrik.de/europe/great-britain-latest.osm.pbf
   
   # Build the routing data
   osrm-extract -p /path/to/osrm-backend/profiles/car.lua great-britain-latest.osm.pbf
   osrm-partition great-britain-latest.osrm
   osrm-customize great-britain-latest.osrm
   
   # Start the OSRM server
   osrm-routed --algorithm mld great-britain-latest.osrm
   ```

2. **Use a public OSRM server** (not recommended for production):
   ```typescript
   <OSRMRouteMap
     route={routeConfig}
     osrmUrl="https://router.project-osrm.org"
   />
   ```

3. **Configure via environment variable:**
   ```bash
   export OSRM_SERVER_URL="http://your-osrm-server:5000"
   ```

## Integration with Existing Code

To integrate this with the existing BetterFleet codebase:

1. **Add to existing map components:**
   Import and use `OSRMRouteMap` alongside existing map components like `BigMap`, `RouteEditor`, etc.

2. **Add to MapRouter:**
   Add a new route in `MapRouter.tsx` to handle OSRM-based routes:
   ```typescript
   <Route path="/routes/osrm/:routeId">
     <OSRMRouteMap route={routeData} showWaypoints={false} />
   </Route>
   ```

3. **Add route editor:**
   Add a route for the interactive route editor:
   ```typescript
   <Route path="/routes/:routeId/edit">
     <RouteEditorWithWaypoints
       initialRoutePoints={routeData}
       stops={stopsData}
       onSave={handleSave}
     />
   </Route>
   ```

4. **Backend integration:**
   Create a Django view or API endpoint that provides route configurations with waypoints:
   ```python
   # Example Django view
   def route_detail(request, route_id):
       route = get_object_or_404(Route, id=route_id)
       return JsonResponse({
           'routePoints': route.route_points  # Array of RoutePoint objects
       })
   ```

## Migration from Legacy Data Model

If you have existing routes using the legacy data model (origin/destination/waypoints), use the `migrateLegacyRouteConfig` function to convert them to the new format:

```typescript
import { migrateLegacyRouteConfig } from "./osrmRouting";

// Legacy format (old)
const legacyRoute = {
  origin: { lat: 51.5074, lng: -0.1278, stopId: 1 },
  destination: { lat: 51.4545, lng: -2.5879, stopId: 2 },
  waypoints: [
    { lat: 51.4700, lng: -0.4543 },
  ],
};

// Migrate to new format
const newRoute = migrateLegacyRouteConfig(legacyRoute);
// Result: { routePoints: [stop, waypoint, stop] }
```

For backend migration, create a Django management command:

```python
# management/commands/migrate_routes.py
from django.core.management.base import BaseCommand
from bustimes.models import Route

class Command(BaseCommand):
    def handle(self, *args, **options):
        routes = Route.objects.all()
        for route in routes:
            if route.origin and route.destination:
                # Convert legacy format to new format
                route_points = []
                route_points.append({
                    'type': 'stop',
                    'lat': route.origin.lat,
                    'lng': route.origin.lng,
                    'stopId': route.origin.id,
                })
                if route.waypoints:
                    for wp in route.waypoints:
                        route_points.append({
                            'type': 'waypoint',
                            'lat': wp.lat,
                            'lng': wp.lng,
                        })
                route_points.append({
                    'type': 'stop',
                    'lat': route.destination.lat,
                    'lng': route.destination.lng,
                    'stopId': route.destination.id,
                })
                route.route_points = route_points
                route.save()
        self.stdout.write(self.style.SUCCESS('Successfully migrated routes'))
```

Run the migration:
```bash
python manage.py migrate_routes
```

## Waypoint Ordering Logic

The waypoint ordering is critical for correct routing. The implementation ensures:

1. **Ordered Sequence**: All route points (stops and waypoints) are visited in the exact order they appear in the `routePoints` array
2. **Mixed Stops and Waypoints**: The sequence can include stops and waypoints in any order (e.g., Stop A → Waypoint 1 → Stop B → Waypoint 2 → Stop C)
3. **OSRM Coordinate Order**: The OSRM request URL is built by concatenating all coordinates in the specified order

This sequence is preserved when building the OSRM request URL, ensuring the route passes through each point in the specified order.

## Testing

To test the implementation:

### Public-Facing Map Test
1. Start an OSRM server (local or public)
2. Create a test page with the `OSRMRouteMap` component
3. Provide a route configuration with waypoints
4. Set `showWaypoints={false}`
5. Verify:
   - The route polyline bends through the waypoints in order
   - Only stop markers are visible
   - Waypoints are not rendered

### Interactive Editor Test
1. Create a test page with the `RouteEditorWithWaypoints` component
2. Provide initial route points and stops data
3. Test clicking on the map to create waypoints
4. Test clicking on existing stops to add them to the route
5. Test selecting, moving, and removing waypoints
6. Verify:
   - Waypoints are created when clicking on non-stop areas
   - Stops are added when clicking on existing stops
   - Waypoints and stops have different visual styles
   - Points can be reordered and removed
   - onSave callback receives the correct route points

## Notes

- Waypoints are **routing hints only** and should not be confused with bus stops
- The OSRM server must support the `/route/v1/driving` endpoint
- The implementation uses GeoJSON format for route geometry
- Coordinates in OSRM use (longitude, latitude) order, which differs from typical (latitude, longitude) order
- On public-facing maps, always use `showWaypoints={false}` to hide waypoint markers
- In editor mode, use `showWaypoints={true}` to show waypoint markers for editing
- The new data model (RoutePoint with type field) is more flexible than the legacy model
