/**
 * OSRM Routing Utility with Waypoint Support
 * 
 * This utility provides functions to fetch routes from an OSRM server
 * with support for ordered waypoints. Waypoints are routing hints only
 * and are not rendered as markers on the map.
 */

// OSRM server URL - configure this to point to your OSRM instance
const OSRM_SERVER_URL = process.env.OSRM_SERVER_URL || "http://localhost:5000";

/**
 * Represents a point in a route, which can be either a stop or a waypoint
 * 
 * Stops are actual bus stops where passengers can board/alight.
 * Waypoints are routing hints only and are not rendered on public maps.
 */
export type RoutePoint = {
  type: "stop" | "waypoint";
  lat: number;
  lng: number;
  stopId?: number; // Only present for stops
};

/**
 * Route configuration as an ordered list of route points
 * 
 * The route is defined as a sequence of stops and waypoints.
 * OSRM will visit each point in the exact order provided.
 */
export type RouteConfig = {
  routePoints: RoutePoint[];
  serviceMode?: string; // Service mode (e.g., "bus", "train") to determine OSRM profile
};

/**
 * Legacy route configuration for backward compatibility
 * @deprecated Use RouteConfig with routePoints instead
 */
export type LegacyRouteConfig = {
  origin: RoutePoint;
  destination: RoutePoint;
  waypoints?: RoutePoint[];
};

/**
 * OSRM route response structure
 */
export type OSRMRouteResponse = {
  code: string;
  routes: Array<{
    geometry: GeoJSON.LineString;
    duration: number;
    distance: number;
  }>;
};

/**
 * Route with stops in database order (for direct OSRM routing)
 * 
 * This structure matches the database/UI representation where stops
 * have longitude, latitude, and name properties.
 */
export type RouteWithStops = {
  stops: Array<{
    longitude: number;
    latitude: number;
    name: string;
  }>;
  serviceMode?: string; // Service mode (e.g., "bus", "train") to determine OSRM profile
};

/**
 * Converts a RoutePoint to OSRM coordinate format (lng,lat)
 */
function pointToOSRMCoordinate(point: RoutePoint): string {
  return `${point.lng},${point.lat}`;
}

/**
 * Builds the ordered coordinate list for OSRM request from route points
 * 
 * The OSRM request must preserve the exact sequence of route points.
 * Each point (whether stop or waypoint) is visited in order:
 * Stop A → Waypoint 1 → Waypoint 2 → Stop B → Waypoint 3 → Stop C
 * 
 * @param config - Route configuration with ordered list of route points
 * @returns Ordered coordinate string for OSRM API
 */
function buildOrderedCoordinates(config: RouteConfig): string {
  const coordinates: string[] = [];
  
  // Add all route points in order (stops and waypoints mixed)
  for (const point of config.routePoints) {
    coordinates.push(pointToOSRMCoordinate(point));
  }
  
  // Join coordinates with semicolons for OSRM format
  // Example: lng1,lat1;lng2,lat2;lng3,lat3
  return coordinates.join(";");
}

/**
 * Migrates a legacy route configuration to the new format
 * 
 * @param legacyConfig - Legacy route configuration with origin/destination/waypoints
 * @returns New route configuration with ordered route points
 */
export function migrateLegacyRouteConfig(legacyConfig: LegacyRouteConfig): RouteConfig {
  const routePoints: RoutePoint[] = [];
  
  // Add origin as a stop
  routePoints.push({
    type: "stop",
    lat: legacyConfig.origin.lat,
    lng: legacyConfig.origin.lng,
    stopId: legacyConfig.origin.stopId,
  });
  
  // Add waypoints in order
  if (legacyConfig.waypoints && legacyConfig.waypoints.length > 0) {
    for (const waypoint of legacyConfig.waypoints) {
      routePoints.push({
        type: "waypoint",
        lat: waypoint.lat,
        lng: waypoint.lng,
      });
    }
  }
  
  // Add destination as a stop
  routePoints.push({
    type: "stop",
    lat: legacyConfig.destination.lat,
    lng: legacyConfig.destination.lng,
    stopId: legacyConfig.destination.stopId,
  });
  
  return { routePoints };
}

/**
 * Migrates a stop-only route (no waypoints) to the new format
 * 
 * This is useful for migrating existing routes that only have origin and destination stops.
 * 
 * @param origin - Origin stop coordinates and ID
 * @param destination - Destination stop coordinates and ID
 * @returns New route configuration with ordered route points
 */
export function migrateStopOnlyRoute(
  origin: { lat: number; lng: number; stopId: number },
  destination: { lat: number; lng: number; stopId: number },
): RouteConfig {
  return {
    routePoints: [
      {
        type: "stop",
        lat: origin.lat,
        lng: origin.lng,
        stopId: origin.stopId,
      },
      {
        type: "stop",
        lat: destination.lat,
        lng: destination.lng,
        stopId: destination.stopId,
      },
    ],
  };
}

/**
 * Fetches a route from OSRM server with waypoint support
 * 
 * This function follows the exact order of route points as provided.
 * It does NOT sort, optimize, or reorder points in any way.
 * Uses OSRM Route Service (/route/v1) only - never Trip Service.
 * 
 * @param config - Route configuration with ordered list of route points
 * @param osrmUrl - Optional custom OSRM server URL
 * @returns Promise resolving to OSRM route response
 * @throws Error if the OSRM request fails
 */
export async function fetchOSRMRoute(
  config: RouteConfig,
  osrmUrl: string = OSRM_SERVER_URL,
): Promise<OSRMRouteResponse> {
  // Log the route point order being sent to OSRM for verification
  console.log(config.routePoints.map((point, index) => `${index}: ${point.type} (${point.lng},${point.lat})`));
  
  // Build the ordered coordinate sequence
  const coordinates = buildOrderedCoordinates(config);
  
  // Determine OSRM profile based on service mode
  // Use "rail" for train services, "driving" for everything else (default)
  const profile = config.serviceMode === "train" ? "rail" : "driving";
  
  // Build the OSRM request URL
  // Format: /route/v1/{profile}/{lng1},{lat1};{lng2},{lat2};{lng3},{lat3}?overview=full&geometries=geojson
  const url = `${osrmUrl}/route/v1/${profile}/${coordinates}?overview=full&geometries=geojson`;
  
  try {
    const response = await fetch(url, {
      method: "GET",
      headers: {
        "Accept": "application/json",
      },
    });
    
    if (!response.ok) {
      throw new Error(`OSRM request failed with status ${response.status}`);
    }
    
    const data = (await response.json()) as OSRMRouteResponse;
    
    if (data.code !== "Ok") {
      throw new Error(`OSRM returned error code: ${data.code}`);
    }
    
    return data;
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(`Failed to fetch OSRM route: ${error.message}`);
    }
    throw new Error("Failed to fetch OSRM route: Unknown error");
  }
}

/**
 * Fetches a route from OSRM server using stops in exact database order
 * 
 * This function follows the exact order of stops as stored in the route.
 * It does NOT sort, optimize, or reorder stops in any way.
 * Uses OSRM Route Service (/route/v1) only - never Trip Service.
 * 
 * @param route - Route with stops in database order
 * @param osrmUrl - Optional custom OSRM server URL
 * @returns Promise resolving to OSRM route response
 * @throws Error if the OSRM request fails
 */
export async function fetchOSRMRouteFromStops(
  route: RouteWithStops,
  osrmUrl: string = OSRM_SERVER_URL,
): Promise<OSRMRouteResponse> {
  // Log the stop order being sent to OSRM for verification
  console.log(route.stops.map(stop => stop.name));
  
  // Build the coordinate string directly from the ordered stop list
  // Coordinates are passed to OSRM in the exact order they appear in the database/UI
  const coordinates = route.stops
    .map(stop => `${stop.longitude},${stop.latitude}`)
    .join(";");
  
  // Determine OSRM profile based on service mode
  // Use "rail" for train services, "driving" for everything else (default)
  const profile = route.serviceMode === "train" ? "rail" : "driving";
  
  // Build the OSRM request URL using Route Service (not Trip Service)
  // Format: /route/v1/{profile}/{lng1},{lat1};{lng2},{lat2};{lng3},{lat3}?overview=full&geometries=geojson
  const url = `${osrmUrl}/route/v1/${profile}/${coordinates}?overview=full&geometries=geojson`;
  
  try {
    const response = await fetch(url, {
      method: "GET",
      headers: {
        "Accept": "application/json",
      },
    });
    
    if (!response.ok) {
      throw new Error(`OSRM request failed with status ${response.status}`);
    }
    
    const data = (await response.json()) as OSRMRouteResponse;
    
    if (data.code !== "Ok") {
      throw new Error(`OSRM returned error code: ${data.code}`);
    }
    
    return data;
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(`Failed to fetch OSRM route: ${error.message}`);
    }
    throw new Error("Failed to fetch OSRM route: Unknown error");
  }
}

/**
 * Extracts the route geometry from OSRM response
 * 
 * @param response - OSRM route response
 * @returns GeoJSON LineString representing the route
 */
export function extractRouteGeometry(
  response: OSRMRouteResponse,
): GeoJSON.LineString | null {
  if (response.routes && response.routes.length > 0) {
    return response.routes[0].geometry;
  }
  return null;
}

/**
 * Gets the route distance in meters from OSRM response
 * 
 * @param response - OSRM route response
 * @returns Distance in meters, or null if not available
 */
export function getRouteDistance(response: OSRMRouteResponse): number | null {
  if (response.routes && response.routes.length > 0) {
    return response.routes[0].distance;
  }
  return null;
}

/**
 * Gets the route duration in seconds from OSRM response
 * 
 * @param response - OSRM route response
 * @returns Duration in seconds, or null if not available
 */
export function getRouteDuration(response: OSRMRouteResponse): number | null {
  if (response.routes && response.routes.length > 0) {
    return response.routes[0].duration;
  }
  return null;
}
