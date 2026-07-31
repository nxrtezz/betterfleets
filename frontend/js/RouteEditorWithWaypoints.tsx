import React, { useState, useEffect, useCallback, useMemo } from "react";
import {
  Layer,
  Source,
  type LayerProps,
  type MapLayerMouseEvent,
} from "react-map-gl/maplibre";

import BusTimesMap from "./Map";
import { getBounds } from "./utils";
import type { RoutePoint } from "./osrmRouting";

/**
 * Route Editor with Interactive Waypoint Placement
 * 
 * This component allows editors to:
 * - Click on existing stops to select them
 * - Click anywhere on the map to create new waypoints
 * - Drag waypoints to move them
 * - Remove waypoints
 * - Reorder route points
 * 
 * Waypoints are distinct from stops and use different visual styles.
 * On public-facing maps, waypoints are hidden.
 */

type StopFeature = GeoJSON.Feature<
  GeoJSON.Point,
  {
    atco_code: string;
    name: string;
    bearing?: number | null;
    url: string;
    services?: string[];
  }
>;

type RouteEditorWithWaypointsProps = {
  initialRoutePoints?: RoutePoint[];
  stops?: GeoJSON.FeatureCollection<GeoJSON.Point, StopFeature["properties"]>;
  onSave?: (routePoints: RoutePoint[]) => void;
  osrmUrl?: string;
};

export default function RouteEditorWithWaypoints({
  initialRoutePoints = [],
  stops,
  onSave,
  osrmUrl,
}: RouteEditorWithWaypointsProps) {
  const [routePoints, setRoutePoints] = useState<RoutePoint[]>(initialRoutePoints);
  const [selectedPointIndex, setSelectedPointIndex] = useState<number | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [message, setMessage] = useState<string>();

  // Calculate bounds for the map
  const bounds = useMemo(() => {
    const coordinates = routePoints.map((point) => [point.lng, point.lat] as [number, number]);
    return getBounds(coordinates, (coord) => coord);
  }, [routePoints]);

  // Create GeoJSON for route points (stops and waypoints)
  const routePointsGeoJson = useMemo(() => {
    return {
      type: "FeatureCollection" as const,
      features: routePoints.map((point, index) => ({
        type: "Feature" as const,
        geometry: {
          type: "Point" as const,
          coordinates: [point.lng, point.lat],
        },
        properties: {
          type: point.type,
          index,
          stopId: point.stopId,
          selected: index === selectedPointIndex,
        },
      })),
    };
  }, [routePoints, selectedPointIndex]);

  // Create GeoJSON for existing stops (for reference)
  const stopsGeoJson = useMemo(() => {
    if (!stops) return null;
    return stops;
  }, [stops]);

  // Layer styles
  const routePointLayer: LayerProps = {
    id: "route-editor-points",
    type: "circle",
    paint: {
      // Different colors for stops vs waypoints
      "circle-color": [
        "case",
        ["boolean", ["get", "selected"], false],
        "#ff6b6b", // Selected point
        ["match", ["get", "type"], "stop", "#d13c2e", "waypoint", "#2b6cb0", "#666"],
      ],
      "circle-radius": [
        "case",
        ["boolean", ["get", "selected"], false],
        10, // Selected point
        ["match", ["get", "type"], "stop", 8, "waypoint", 6, 8],
      ],
      "circle-stroke-width": 2,
      "circle-stroke-color": "#fff",
      "circle-opacity": ["match", ["get", "type"], "stop", 1, "waypoint", 0.8, 1],
    },
  };

  const stopLayer: LayerProps = {
    id: "route-editor-stops",
    type: "symbol",
    layout: {
      "icon-rotate": ["+", 45, ["get", "bearing"]],
      "icon-image": [
        "case",
        ["==", ["get", "bearing"], ["literal", null]],
        "route-stop-marker-circle",
        "route-stop-marker",
      ],
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
    },
  };

  const routePointLabelLayer: LayerProps = {
    id: "route-editor-point-labels",
    type: "symbol",
    layout: {
      "text-field": ["match", ["get", "type"], "stop", ["concat", "Stop ", ["get", "index"]], ["concat", "WP ", ["get", "index"]]],
      "text-font": ["Open Sans Semibold", "Arial Unicode MS Bold"],
      "text-size": 11,
      "text-offset": [0, 1.5],
      "text-anchor": "top",
    },
    paint: {
      "text-color": "#333",
      "text-halo-color": "#fff",
      "text-halo-width": 2,
    },
  };

  // Handle map click - create waypoint or select stop
  const handleMapClick = useCallback(
    (event: MapLayerMouseEvent) => {
      // Check if a stop was clicked
      if (event.features && event.features.length > 0) {
        for (const feature of event.features) {
          if (feature.layer.id === "route-editor-stops") {
            // A stop was clicked - select it
            const atcoCode = feature.properties.atco_code;
            const stopFeature = stops?.features.find((s) => s.properties.atco_code === atcoCode);
            if (stopFeature) {
              const [lng, lat] = stopFeature.geometry.coordinates as [number, number];
              const newRoutePoint: RoutePoint = {
                type: "stop",
                lat,
                lng,
                stopId: parseInt(atcoCode, 10),
              };
              
              // Add stop to route points at the end
              setRoutePoints((prev) => [...prev, newRoutePoint]);
              setMessage(`Added stop: ${stopFeature.properties.name}`);
              setSelectedPointIndex(routePoints.length);
              return;
            }
          }
        }
      }

      // No stop was clicked - create a waypoint
      const newWaypoint: RoutePoint = {
        type: "waypoint",
        lat: event.lngLat.lat,
        lng: event.lngLat.lng,
      };

      // Add waypoint to route points at the end
      setRoutePoints((prev) => [...prev, newWaypoint]);
      setMessage(`Added waypoint at ${event.lngLat.lat.toFixed(6)}, ${event.lngLat.lng.toFixed(6)}`);
      setSelectedPointIndex(routePoints.length);
    },
    [stops, routePoints.length],
  );

  // Handle point selection
  const handlePointClick = useCallback(
    (event: MapLayerMouseEvent) => {
      if (event.features && event.features.length > 0) {
        const feature = event.features[0];
        if (feature.layer.id === "route-editor-points") {
          const index = feature.properties.index as number;
          setSelectedPointIndex(index);
          event.stopPropagation(); // Prevent map click handler
        }
      }
    },
    [],
  );

  // Remove selected point
  const removeSelectedPoint = useCallback(() => {
    if (selectedPointIndex !== null) {
      const point = routePoints[selectedPointIndex];
      setRoutePoints((prev) => prev.filter((_, i) => i !== selectedPointIndex));
      setMessage(`Removed ${point.type} at index ${selectedPointIndex}`);
      setSelectedPointIndex(null);
    }
  }, [selectedPointIndex, routePoints]);

  // Move selected point up in sequence
  const movePointUp = useCallback(() => {
    if (selectedPointIndex !== null && selectedPointIndex > 0) {
      setRoutePoints((prev) => {
        const newPoints = [...prev];
        [newPoints[selectedPointIndex], newPoints[selectedPointIndex - 1]] = [
          newPoints[selectedPointIndex - 1],
          newPoints[selectedPointIndex],
        ];
        return newPoints;
      });
      setSelectedPointIndex(selectedPointIndex - 1);
    }
  }, [selectedPointIndex]);

  // Move selected point down in sequence
  const movePointDown = useCallback(() => {
    if (selectedPointIndex !== null && selectedPointIndex < routePoints.length - 1) {
      setRoutePoints((prev) => {
        const newPoints = [...prev];
        [newPoints[selectedPointIndex], newPoints[selectedPointIndex + 1]] = [
          newPoints[selectedPointIndex + 1],
          newPoints[selectedPointIndex],
        ];
        return newPoints;
      });
      setSelectedPointIndex(selectedPointIndex + 1);
    }
  }, [selectedPointIndex, routePoints.length]);

  // Save route points
  const handleSave = useCallback(() => {
    if (onSave) {
      onSave(routePoints);
      setMessage("Route points saved");
    }
  }, [routePoints, onSave]);

  return (
    <div className="route-editor-waypoints">
      <div className="route-editor-waypoints__toolbar">
        <h3>Route Editor with Waypoints</h3>
        <div className="route-editor-waypoints__controls">
          <button
            type="button"
            className="button"
            onClick={removeSelectedPoint}
            disabled={selectedPointIndex === null}
          >
            Remove Selected
          </button>
          <button
            type="button"
            className="button"
            onClick={movePointUp}
            disabled={selectedPointIndex === null || selectedPointIndex === 0}
          >
            Move Up
          </button>
          <button
            type="button"
            className="button"
            onClick={movePointDown}
            disabled={selectedPointIndex === null || selectedPointIndex === routePoints.length - 1}
          >
            Move Down
          </button>
          <button type="button" className="button" onClick={handleSave}>
            Save Route
          </button>
        </div>
      </div>

      {message && <p className="route-editor-waypoints__message">{message}</p>}

      <div className="route-editor-waypoints__info">
        <p>
          <strong>Instructions:</strong>
        </p>
        <ul>
          <li>Click on an existing stop to add it to the route</li>
          <li>Click anywhere on the map to create a waypoint</li>
          <li>Click on a route point to select it</li>
          <li>Use controls to remove or reorder points</li>
          <li>Stops are shown in red, waypoints in blue</li>
        </ul>
      </div>

      <div className="route-editor-waypoints__map">
        {bounds ? (
          <BusTimesMap
            initialViewState={{
              bounds: [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()],
              fitBoundsOptions: {
                padding: { top: 50, bottom: 50, left: 50, right: 50 },
              },
            }}
            onClick={handleMapClick}
            interactiveLayerIds={["route-editor-points", "route-editor-stops"]}
          >
            {/* Render existing stops for reference */}
            {stopsGeoJson && (
              <Source type="geojson" data={stopsGeoJson}>
                <Layer {...stopLayer} />
              </Source>
            )}

            {/* Render route points (stops and waypoints) */}
            <Source type="geojson" data={routePointsGeoJson}>
              <Layer {...routePointLayer} onClick={handlePointClick} />
              <Layer {...routePointLabelLayer} />
            </Source>
          </BusTimesMap>
        ) : (
          <p>No route points to display</p>
        )}
      </div>

      <div className="route-editor-waypoints__list">
        <h4>Route Points ({routePoints.length})</h4>
        <ul>
          {routePoints.map((point, index) => (
            <li
              key={index}
              className={`route-editor-waypoints__list-item${
                index === selectedPointIndex ? " is-selected" : ""
              }`}
              onClick={() => setSelectedPointIndex(index)}
            >
              <span className="route-editor-waypoints__list-item-type">
                {point.type === "stop" ? "🛑" : "📍"}
              </span>
              <span className="route-editor-waypoints__list-item-index">{index}:</span>
              <span className="route-editor-waypoints__list-item-coords">
                {point.lat.toFixed(6)}, {point.lng.toFixed(6)}
              </span>
              {point.stopId && (
                <span className="route-editor-waypoints__list-item-stopid">
                  (Stop ID: {point.stopId})
                </span>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
