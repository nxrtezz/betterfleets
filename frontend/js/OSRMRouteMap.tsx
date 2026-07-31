import React, { useState, useEffect, useMemo } from "react";

import { Layer, Source, type LayerProps } from "react-map-gl/maplibre";

import BusTimesMap from "./Map";
import { getBounds } from "./utils";
import {
  fetchOSRMRoute,
  extractRouteGeometry,
  type RouteConfig,
  type RoutePoint,
} from "./osrmRouting";

/**
 * OSRM Route Map Component
 * 
 * This component displays a route defined by an ordered list of route points
 * (stops and waypoints). On public-facing maps, waypoints are not rendered as
 * markers - only stops are visible. The route polyline passes through all points
 * in the specified order.
 * 
 * Example usage:
 * ```tsx
 * <OSRMRouteMap
 *   route={{
 *     routePoints: [
 *       { type: "stop", lat: 51.5074, lng: -0.1278, stopId: 1 },      // London
 *       { type: "waypoint", lat: 51.4700, lng: -0.4543 },             // Hidden routing guide
 *       { type: "waypoint", lat: 51.3811, lng: -2.3590 },             // Hidden routing guide
 *       { type: "stop", lat: 51.4545, lng: -2.5879, stopId: 2 },     // Bristol
 *     ],
 *   }}
 *   osrmUrl="http://localhost:5000"
 *   showWaypoints={false} // Hide waypoints on public-facing maps
 * />
 * ```
 */

type OSRMRouteMapProps = {
  route: RouteConfig;
  osrmUrl?: string;
  showWaypoints?: boolean; // If true, show waypoint markers (for editor mode)
};

export default function OSRMRouteMap({
  route,
  osrmUrl,
  showWaypoints = false,
}: OSRMRouteMapProps) {
  const [routeGeometry, setRouteGeometry] = useState<GeoJSON.LineString | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch route from OSRM when route config changes
  useEffect(() => {
    let isCancelled = false;

    setLoading(true);
    setError(null);
    setRouteGeometry(null);

    fetchOSRMRoute(route, osrmUrl)
      .then((response) => {
        if (isCancelled) return;
        
        const geometry = extractRouteGeometry(response);
        if (geometry) {
          setRouteGeometry(geometry);
        } else {
          setError("No route geometry found in OSRM response");
        }
        setLoading(false);
      })
      .catch((err) => {
        if (isCancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load route");
        setLoading(false);
      });

    return () => {
      isCancelled = true;
    };
  }, [route, osrmUrl]);

  // Calculate bounds for the route
  const bounds = useMemo(() => {
    if (!routeGeometry) return null;
    
    const coordinates = routeGeometry.coordinates;
    return getBounds(coordinates, (coord) => coord);
  }, [routeGeometry]);

  // Create GeoJSON for route line
  const routeGeoJson = useMemo(() => {
    if (!routeGeometry) return null;
    
    return {
      type: "FeatureCollection" as const,
      features: [
        {
          type: "Feature" as const,
          geometry: routeGeometry,
          properties: null,
        },
      ],
    };
  }, [routeGeometry]);

  // Create GeoJSON for stop markers
  // If showWaypoints is false, only render stops (not waypoints)
  // If showWaypoints is true, render both stops and waypoints (for editor mode)
  const stopsGeoJson = useMemo(() => {
    const features = route.routePoints
      .filter((point) => point.type === "stop" || showWaypoints)
      .map((point, index) => ({
        type: "Feature" as const,
        geometry: {
          type: "Point" as const,
          coordinates: [point.lng, point.lat],
        },
        properties: {
          type: point.type,
          index,
          stopId: point.stopId,
        },
      }));

    return {
      type: "FeatureCollection" as const,
      features,
    };
  }, [route, showWaypoints]);

  // Layer styles
  const routeLayer: LayerProps = {
    id: "osrm-route-line",
    type: "line",
    paint: {
      "line-color": "#2b6cb0",
      "line-width": 4,
      "line-opacity": 0.8,
    },
  };

  const stopLayer: LayerProps = {
    id: "osrm-route-stops",
    type: "circle",
    paint: {
      // Different colors for stops vs waypoints
      "circle-color": ["match", ["get", "type"], "stop", "#d13c2e", "waypoint", "#2b6cb0", "#666"],
      "circle-radius": ["match", ["get", "type"], "stop", 8, "waypoint", 6, 8],
      "circle-stroke-width": 2,
      "circle-stroke-color": "#fff",
      "circle-opacity": ["match", ["get", "type"], "stop", 1, "waypoint", 0.8, 1],
    },
  };

  const stopLabelLayer: LayerProps = {
    id: "osrm-route-stop-labels",
    type: "symbol",
    layout: {
      "text-field": ["match", ["get", "type"], "stop", ["concat", "Stop ", ["get", "index"]], ["concat", "WP ", ["get", "index"]]],
      "text-font": ["Open Sans Semibold", "Arial Unicode MS Bold"],
      "text-size": 12,
      "text-offset": [0, 1.5],
      "text-anchor": "top",
    },
    paint: {
      "text-color": "#333",
      "text-halo-color": "#fff",
      "text-halo-width": 2,
    },
  };

  if (loading) {
    return <div className="osrm-route-map">Loading route...</div>;
  }

  if (error) {
    return <div className="osrm-route-map error">Error: {error}</div>;
  }

  if (!bounds || !routeGeoJson) {
    return <div className="osrm-route-map">No route available</div>;
  }

  return (
    <div className="osrm-route-map">
      <div className="depot-map osrm-route-map__canvas">
        <BusTimesMap
          initialViewState={{
            bounds: [
              bounds.getWest(),
              bounds.getSouth(),
              bounds.getEast(),
              bounds.getNorth(),
            ],
            fitBoundsOptions: {
              padding: { top: 50, bottom: 50, left: 50, right: 50 },
            },
          }}
        >
          {/* Render the route polyline */}
          <Source type="geojson" data={routeGeoJson}>
            <Layer {...routeLayer} />
          </Source>

          {/* Render stop markers (and waypoints if showWaypoints is true) */}
          {/* On public maps, waypoints are hidden - they are routing hints only */}
          <Source type="geojson" data={stopsGeoJson}>
            <Layer {...stopLayer} />
            {showWaypoints && <Layer {...stopLabelLayer} />}
          </Source>
        </BusTimesMap>
      </div>
    </div>
  );
}
