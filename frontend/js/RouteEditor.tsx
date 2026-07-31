import React from "react";
import {
  Layer,
  Source,
  type LayerProps,
  type MapLayerMouseEvent,
} from "react-map-gl/maplibre";

import BusTimesMap from "./Map";
import { getBounds } from "./utils";

declare global {
  interface Window {
    EXTENT: [number, number, number, number];
  }
}

type SearchResult = {
  id: number;
  line_name: string;
  description: string;
  service_code: string;
  slug: string;
  url: string;
  operators: string[];
};

type Segment = {
  id: string;
  line_name: string;
  inbound: boolean;
  from_stop_id: string;
  to_stop_id: string;
  from_stop_name: string;
  to_stop_name: string;
  from_stop_coordinates: [number, number];
  to_stop_coordinates: [number, number];
  coordinates: [number, number][];
  has_route_link: boolean;
  override: boolean;
  waypoints: Array<{
    id: number;
    latitude: number;
    longitude: number;
    order: number;
  }>;
};

type StopFeature = GeoJSON.Feature<
  GeoJSON.Point,
  {
    atco_code: string;
    naptan_code?: string | null;
    name: string;
    bearing?: number | null;
    url: string;
    services?: string[];
  }
>;

type RouteEditorData = {
  service: {
    id: number;
    line_name: string;
    description: string;
    service_code: string;
    slug: string;
    url: string;
    operators: string[];
  };
  stops: GeoJSON.FeatureCollection<GeoJSON.Point, StopFeature["properties"]>;
  segments: Segment[];
};

function getCookie(name: string) {
  const cookies = document.cookie ? document.cookie.split("; ") : [];
  for (const cookie of cookies) {
    const [key, ...rest] = cookie.split("=");
    if (key === name) {
      return decodeURIComponent(rest.join("="));
    }
  }
}

function formatCoordinates(coordinates: [number, number][]) {
  return coordinates
    .map(([lng, lat]) => `${lng.toFixed(6)}, ${lat.toFixed(6)}`)
    .join("\n");
}

function parseCoordinates(
  value: string,
  fallbackFrom: [number, number],
  fallbackTo: [number, number],
) {
  const lines = value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  if (!lines.length) {
    return [];
  }

  const coordinates: [number, number][] = [];
  for (const line of lines) {
    const parts = line.split(",").map((part) => part.trim());
    if (parts.length !== 2) {
      return null;
    }
    const lng = Number.parseFloat(parts[0]);
    const lat = Number.parseFloat(parts[1]);
    if (Number.isNaN(lng) || Number.isNaN(lat)) {
      return null;
    }
    coordinates.push([lng, lat]);
  }

  if (coordinates.length === 1) {
    return [fallbackFrom, coordinates[0], fallbackTo];
  }

  return coordinates;
}

function withEndpoints(segment: Segment, coordinates: [number, number][]) {
  if (!coordinates.length) {
    return [];
  }

  const result = [...coordinates];
  const [firstLng, firstLat] = result[0];
  const [startLng, startLat] = segment.from_stop_coordinates;
  if (firstLng !== startLng || firstLat !== startLat) {
    result.unshift(segment.from_stop_coordinates);
  }

  const last = result[result.length - 1];
  const [endLng, endLat] = segment.to_stop_coordinates;
  if (last[0] !== endLng || last[1] !== endLat) {
    result.push(segment.to_stop_coordinates);
  }

  return result;
}

export default function RouteEditor({
  initialServiceId,
}: {
  initialServiceId?: number;
}) {
  const [query, setQuery] = React.useState("");
  const [results, setResults] = React.useState<SearchResult[]>([]);
  const [searching, setSearching] = React.useState(false);
  const [selectedServiceId, setSelectedServiceId] = React.useState<number | undefined>(
    initialServiceId,
  );
  const [data, setData] = React.useState<RouteEditorData>();
  const [loading, setLoading] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [message, setMessage] = React.useState<string>();
  const [error, setError] = React.useState<string>();
  const [selectedSegmentId, setSelectedSegmentId] = React.useState<string>();
  const [waypointMode, setWaypointMode] = React.useState(false);
  const [stopSearchQuery, setStopSearchQuery] = React.useState("");

  React.useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      return;
    }

    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      setSearching(true);
      fetch(`/services/route-editor/search?q=${encodeURIComponent(query.trim())}`, {
        signal: controller.signal,
      }).then(
        async (response) => {
          if (!response.ok) {
            throw new Error(`Search failed with ${response.status}`);
          }
          const payload = (await response.json()) as { results: SearchResult[] };
          setResults(payload.results);
          setSearching(false);
        },
        (err: unknown) => {
          if (controller.signal.aborted) {
            return;
          }
          setSearching(false);
          setError(err instanceof Error ? err.message : "Search failed.");
        },
      );
    }, 250);

    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [query]);

  React.useEffect(() => {
    if (!selectedServiceId) {
      setData(undefined);
      return;
    }

    setLoading(true);
    setError(undefined);
    setMessage(undefined);

    fetch(`/services/${selectedServiceId}/route-editor.json`).then(
      async (response) => {
        if (!response.ok) {
          throw new Error(`Could not load service ${selectedServiceId}.`);
        }
        const payload = (await response.json()) as RouteEditorData;
        setData(payload);
        setSelectedSegmentId(payload.segments[0]?.id);
        setLoading(false);
        const nextUrl = new URL(window.location.href);
        nextUrl.searchParams.set("service", String(selectedServiceId));
        window.history.replaceState({}, "", nextUrl.toString());
      },
      (err: unknown) => {
        setLoading(false);
        setError(err instanceof Error ? err.message : "Failed to load route editor data.");
      },
    );
  }, [selectedServiceId]);

  const updateSegment = React.useCallback((segmentId: string, updater: (segment: Segment) => Segment) => {
    setData((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        segments: current.segments.map((segment: Segment) =>
          segment.id === segmentId ? updater(segment) : segment,
        ),
      };
    });
  }, []);

  const selectedSegment = React.useMemo(
    () => data?.segments.find((segment: Segment) => segment.id === selectedSegmentId),
    [data, selectedSegmentId],
  );

  const allCoordinates = React.useMemo(() => {
    const points =
      data?.stops.features.map(
        (feature) => feature.geometry.coordinates as [number, number],
      ) || [];
    for (const segment of data?.segments || []) {
      points.push(...segment.coordinates);
    }
    return points;
  }, [data]);

  const bounds = React.useMemo(
    () => getBounds(allCoordinates, (coord) => coord),
    [allCoordinates],
  );

  React.useEffect(() => {
    if (bounds) {
      window.EXTENT = [
        bounds.getWest(),
        bounds.getSouth(),
        bounds.getEast(),
        bounds.getNorth(),
      ];
    }
  }, [bounds]);

  const segmentsGeoJson = React.useMemo<GeoJSON.FeatureCollection>(() => {
    return {
      type: "FeatureCollection",
      features: (data?.segments || [])
        .filter((segment) => segment.coordinates.length >= 2)
        .map((segment) => ({
          type: "Feature",
          geometry: {
            type: "LineString",
            coordinates: segment.coordinates,
          },
          properties: {
            id: segment.id,
            selected: segment.id === selectedSegmentId,
          },
        })),
    };
  }, [data, selectedSegmentId]);

  const selectedPointsGeoJson = React.useMemo<GeoJSON.FeatureCollection>(() => {
    return {
      type: "FeatureCollection",
      features: (selectedSegment?.coordinates || []).map((coordinate, index) => ({
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: coordinate,
        },
        properties: {
          id: `${selectedSegment?.id || "segment"}:${index}`,
        },
      })),
    };
  }, [selectedSegment]);

  const waypointsGeoJson = React.useMemo<GeoJSON.FeatureCollection>(() => {
    return {
      type: "FeatureCollection",
      features: (selectedSegment?.waypoints || []).map((waypoint: Segment["waypoints"][0]) => ({
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: [waypoint.longitude, waypoint.latitude],
        },
        properties: {
          id: waypoint.id,
          order: waypoint.order,
        },
      })),
    };
  }, [selectedSegment]);

  const filteredStopsGeoJson = React.useMemo<GeoJSON.FeatureCollection>(() => {
    if (!data || !stopSearchQuery.trim()) {
      return data?.stops || { type: "FeatureCollection", features: [] };
    }

    const query = stopSearchQuery.toLowerCase();
    const filteredFeatures = data.stops.features.filter((feature: StopFeature) => {
      const name = feature.properties.name?.toLowerCase() || "";
      const naptanCode = feature.properties.naptan_code?.toLowerCase() || "";
      const atcoCode = feature.properties.atco_code?.toLowerCase() || "";
      return name.includes(query) || naptanCode.includes(query) || atcoCode.includes(query);
    });

    return {
      type: "FeatureCollection",
      features: filteredFeatures,
    };
  }, [data, stopSearchQuery]);

  const lineLayer: LayerProps = {
    id: "route-editor-lines",
    type: "line",
    paint: {
      "line-color": [
        "case",
        ["boolean", ["get", "selected"], false],
        "#d13c2e",
        "#2b6cb0",
      ],
      "line-width": [
        "case",
        ["boolean", ["get", "selected"], false],
        5,
        3,
      ],
    },
  };

  const pointLayer: LayerProps = {
    id: "route-editor-points",
    type: "circle",
    paint: {
      "circle-color": "#d13c2e",
      "circle-radius": 5,
      "circle-stroke-width": 2,
      "circle-stroke-color": "#fff",
    },
  };

  const waypointLayer: LayerProps = {
    id: "route-editor-waypoints",
    type: "circle",
    paint: {
      "circle-color": "#2b6cb0",
      "circle-radius": 8,
      "circle-stroke-width": 3,
      "circle-stroke-color": "#fff",
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

  const handleMapClick = React.useCallback(
    (event: MapLayerMouseEvent) => {
      if (!selectedSegment) {
        return;
      }

      if (waypointMode) {
        // Add a routing waypoint (stored in waypoints array)
        const newWaypoint = {
          id: Date.now(), // Temporary ID for new waypoints
          latitude: event.lngLat.lat,
          longitude: event.lngLat.lng,
          order: (selectedSegment.waypoints?.length || 0),
        };
        updateSegment(selectedSegment.id, (segment: Segment) => {
          return {
            ...segment,
            waypoints: [...(segment.waypoints || []), newWaypoint],
          };
        });
        setMessage(`Added routing waypoint to ${selectedSegment.from_stop_name} -> ${selectedSegment.to_stop_name}.`);
      } else {
        // Add a manual coordinate waypoint (stored in coordinates array)
        const waypoint: [number, number] = [event.lngLat.lng, event.lngLat.lat];
        updateSegment(selectedSegment.id, (segment: Segment) => {
          const next = [...segment.coordinates];
          if (next.length < 2) {
            return {
              ...segment,
              coordinates: [
                segment.from_stop_coordinates,
                waypoint,
                segment.to_stop_coordinates,
              ],
            };
          }
          next.splice(next.length - 1, 0, waypoint);
          return {
            ...segment,
            coordinates: next,
          };
        });
        setMessage(`Added manual waypoint to ${selectedSegment.from_stop_name} -> ${selectedSegment.to_stop_name}.`);
      }
    },
    [selectedSegment, updateSegment, waypointMode],
  );

  const handleSave = React.useCallback(() => {
    if (!selectedServiceId || !data) {
      return;
    }

    setSaving(true);
    setError(undefined);
    setMessage(undefined);

    fetch(`/services/${selectedServiceId}/route-editor/save`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCookie("csrftoken") || "",
      },
      body: JSON.stringify({
        segments: data.segments.map((segment: Segment) => ({
          from_stop_id: segment.from_stop_id,
          to_stop_id: segment.to_stop_id,
          coordinates: segment.coordinates,
          waypoints: segment.waypoints || [],
        })),
      }),
    }).then(
      async (response) => {
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || `Save failed with ${response.status}`);
        }
        const payload = (await response.json()) as {
          updated: number;
          created: number;
          deleted: number;
          waypoints_updated: number;
          waypoints_created: number;
          waypoints_deleted: number;
        };
        setSaving(false);
        setMessage(
          `Saved route geometry. Updated ${payload.updated}, created ${payload.created}, deleted ${payload.deleted}. Waypoints: updated ${payload.waypoints_updated}, created ${payload.waypoints_created}, deleted ${payload.waypoints_deleted}.`,
        );
      },
      (err: unknown) => {
        setSaving(false);
        setError(err instanceof Error ? err.message : "Save failed.");
      },
    );
  }, [data, selectedServiceId]);

  const deleteWaypoint = React.useCallback((waypointId: number) => {
    if (!selectedSegment) return;
    updateSegment(selectedSegment.id, (segment: Segment) => {
      return {
        ...segment,
        waypoints: segment.waypoints?.filter((wp) => wp.id !== waypointId) || [],
      };
    });
    setMessage("Deleted waypoint.");
  }, [selectedSegment, updateSegment]);

  const moveWaypointUp = React.useCallback((waypointId: number) => {
    if (!selectedSegment) return;
    updateSegment(selectedSegment.id, (segment: Segment) => {
      const waypoints = segment.waypoints || [];
      const index = waypoints.findIndex((wp) => wp.id === waypointId);
      if (index <= 0) return segment;
      
      const newWaypoints = [...waypoints];
      [newWaypoints[index], newWaypoints[index - 1]] = [newWaypoints[index - 1], newWaypoints[index]];
      
      // Update order values
      newWaypoints.forEach((wp, i) => wp.order = i);
      
      return {
        ...segment,
        waypoints: newWaypoints,
      };
    });
    setMessage("Moved waypoint up.");
  }, [selectedSegment, updateSegment]);

  const moveWaypointDown = React.useCallback((waypointId: number) => {
    if (!selectedSegment) return;
    updateSegment(selectedSegment.id, (segment: Segment) => {
      const waypoints = segment.waypoints || [];
      const index = waypoints.findIndex((wp) => wp.id === waypointId);
      if (index === -1 || index >= waypoints.length - 1) return segment;
      
      const newWaypoints = [...waypoints];
      [newWaypoints[index], newWaypoints[index + 1]] = [newWaypoints[index + 1], newWaypoints[index]];
      
      // Update order values
      newWaypoints.forEach((wp, i) => wp.order = i);
      
      return {
        ...segment,
        waypoints: newWaypoints,
      };
    });
    setMessage("Moved waypoint down.");
  }, [selectedSegment, updateSegment]);

  return (
    <div className="route-editor">
      <div className="route-editor__toolbar">
        <label className="route-editor__search">
          <span>Service</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search line name, description or service code"
          />
        </label>
        {data && (
          <label className="route-editor__search">
            <span>Stops</span>
            <input
              type="search"
              value={stopSearchQuery}
              onChange={(event) => setStopSearchQuery(event.target.value)}
              placeholder="Search stop name or NaPTAN code"
            />
          </label>
        )}
        <button
          type="button"
          className={`button ${waypointMode ? "is-active" : ""}`}
          onClick={() => setWaypointMode(!waypointMode)}
          disabled={!data}
        >
          {waypointMode ? "Exit Waypoint Mode" : "Enter Waypoint Mode"}
        </button>
        <button type="button" className="button" onClick={handleSave} disabled={!data || saving}>
          {saving ? "Saving..." : "Save geometry"}
        </button>
      </div>

      {searching ? <p>Searching services...</p> : null}
      {results.length ? (
        <div className="route-editor__results">
          {results.map((result) => (
            <button
              key={result.id}
              type="button"
              className="route-editor__result"
              onClick={() => {
                setSelectedServiceId(result.id);
                setQuery(`${result.line_name} ${result.description}`.trim());
                setResults([]);
              }}
            >
              <strong>{result.line_name}</strong>
              <span>{result.description || result.service_code}</span>
              {result.operators.length ? (
                <small>{result.operators.join(", ")}</small>
              ) : null}
            </button>
          ))}
        </div>
      ) : null}

      {message ? <p className="route-editor__message">{message}</p> : null}
      {error ? <p className="route-editor__error">{error}</p> : null}
      {loading ? <p>Loading route editor...</p> : null}

      {data ? (
        <div className="route-editor__layout">
          <section className="route-editor__panel">
            <h2>
              {data.service.line_name}
              {data.service.description ? ` - ${data.service.description}` : ""}
            </h2>
            <p className="route-editor__meta">
              {data.service.operators.join(", ")}
              {data.service.service_code ? ` | ${data.service.service_code}` : ""}
            </p>
            <p>
              Click a segment below, then click the map to insert waypoints before the end stop.
            </p>
            {waypointMode && (
              <div className="route-editor__waypoint-panel">
                <h4>Routing Waypoints</h4>
                <p className="route-editor__waypoint-info">
                  <strong>Waypoint Mode Active:</strong> Click on the map to add routing waypoints.
                  Waypoints guide OSRM to choose specific roads for this segment.
                </p>
                {selectedSegment && selectedSegment.waypoints && selectedSegment.waypoints.length > 0 ? (
                  <div className="route-editor__waypoint-list">
                    {selectedSegment.waypoints
                      .sort((a: Segment["waypoints"][0], b: Segment["waypoints"][0]) => a.order - b.order)
                      .map((waypoint: Segment["waypoints"][0]) => (
                        <div key={waypoint.id} className="route-editor__waypoint-item">
                          <span className="route-editor__waypoint-order">{waypoint.order}:</span>
                          <span className="route-editor__waypoint-coords">
                            {waypoint.latitude.toFixed(6)}, {waypoint.longitude.toFixed(6)}
                          </span>
                          <div className="route-editor__waypoint-actions">
                            <button
                              type="button"
                              className="button button--small"
                              onClick={() => moveWaypointUp(waypoint.id)}
                              disabled={waypoint.order === 0}
                              title="Move up"
                            >
                              ↑
                            </button>
                            <button
                              type="button"
                              className="button button--small"
                              onClick={() => moveWaypointDown(waypoint.id)}
                              disabled={waypoint.order === (selectedSegment.waypoints?.length || 1) - 1}
                              title="Move down"
                            >
                              ↓
                            </button>
                            <button
                              type="button"
                              className="button button--small button--danger"
                              onClick={() => deleteWaypoint(waypoint.id)}
                              title="Delete"
                            >
                              ×
                            </button>
                          </div>
                        </div>
                      ))}
                  </div>
                ) : (
                  <p className="route-editor__waypoint-empty">No waypoints for this segment.</p>
                )}
              </div>
            )}

            <div className="route-editor__segments">
              {data.segments.map((segment) => (
                <article
                  key={segment.id}
                  className={`route-editor__segment${
                    segment.id === selectedSegmentId ? " is-selected" : ""
                  }`}
                >
                  <button
                    type="button"
                    className="route-editor__segment-header"
                    onClick={() => setSelectedSegmentId(segment.id)}
                  >
                    <strong>
                      {segment.from_stop_name} {"->"} {segment.to_stop_name}
                    </strong>
                    <span>
                      {segment.line_name || data.service.line_name}
                      {segment.inbound ? " inbound" : " outbound"}
                    </span>
                  </button>
                  <textarea
                    value={formatCoordinates(segment.coordinates)}
                    onChange={(event) => {
                      const parsed = parseCoordinates(
                        event.target.value,
                        segment.from_stop_coordinates,
                        segment.to_stop_coordinates,
                      );
                      if (parsed === null) {
                        setError("Coordinates must be one `lng, lat` pair per line.");
                        return;
                      }
                      setError(undefined);
                      updateSegment(segment.id, (current) => ({
                        ...current,
                        coordinates: withEndpoints(current, parsed),
                      }));
                    }}
                    rows={6}
                  />
                  <div className="route-editor__segment-actions">
                    <button
                      type="button"
                      onClick={() =>
                        updateSegment(segment.id, (current) => ({
                          ...current,
                          coordinates: [
                            current.from_stop_coordinates,
                            current.to_stop_coordinates,
                          ],
                        }))
                      }
                    >
                      Straight line
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        updateSegment(segment.id, (current) => ({
                          ...current,
                          coordinates: [],
                        }))
                      }
                    >
                      Clear
                    </button>
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className="route-editor__map">
            <div className="depot-map route-editor__map-canvas">
              {bounds ? (
                <BusTimesMap
                  initialViewState={{
                    bounds: window.EXTENT,
                    fitBoundsOptions: {
                      padding: { top: 20, bottom: 20, left: 20, right: 20 },
                    },
                  }}
                  onClick={handleMapClick}
                >
                  <Source type="geojson" data={segmentsGeoJson}>
                    <Layer {...lineLayer} />
                  </Source>
                  <Source type="geojson" data={filteredStopsGeoJson}>
                    <Layer {...stopLayer} />
                  </Source>
                  <Source type="geojson" data={selectedPointsGeoJson}>
                    <Layer {...pointLayer} />
                  </Source>
                  {waypointMode && waypointsGeoJson && (
                    <Source type="geojson" data={waypointsGeoJson}>
                      <Layer {...waypointLayer} />
                    </Source>
                  )}
                </BusTimesMap>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
