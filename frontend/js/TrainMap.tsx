import React, {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import {
  Layer,
  type MapLayerMouseEvent,
  type ViewStateChangeEvent,
  Source,
} from "react-map-gl/maplibre";
import { Link } from "wouter";
import debounce from "lodash/debounce";

import BusTimesMap from "./Map";
import VehicleMarker from "./VehicleMarker";
import VehiclePopup from "./VehiclePopup";
import {
  getClickedVehicleMarkerId,
  type Vehicle,
} from "./VehicleMarker";

const CLUSTER_THRESHOLD = 80;
const POLL_MS = 15000;
const CLUSTER_MAX_ZOOM = 14;
const CLUSTER_RADIUS = 56;
const MIN_ZOOM_TRAINS = 6;

function trainsJsonUrl(): string {
  const u = window.TRAINS_JSON_URL?.trim();
  return u || "https://transportstatistics.com/api/live-trains/";
}

type TrainPointFeature = {
  type: "Feature";
  id: number;
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: { id: number; colour: string };
};

type TrainFeatureCollection = {
  type: "FeatureCollection";
  features: TrainPointFeature[];
};

function getBoundsQueryString(bounds: {
  getNorth(): number;
  getSouth(): number;
  getEast(): number;
  getWest(): number;
}): string {
  return `?ymax=${bounds.getNorth()}&xmax=${bounds.getEast()}&ymin=${bounds.getSouth()}&xmin=${bounds.getWest()}&showTrains=true`;
}

export type TrainVehicle = Vehicle & {
  route_id?: string;
  trip_descriptor_id?: string;
  start_time?: string;
};

function useSmoothedTrains(raw: TrainVehicle[] | undefined): TrainVehicle[] {
  const targetsRef = useRef<Map<number, TrainVehicle>>(new Map());
  const [smoothed, setSmoothed] = useState<TrainVehicle[]>([]);

  useEffect(() => {
    if (!raw?.length) {
      targetsRef.current = new Map();
      setSmoothed([]);
      return;
    }
    targetsRef.current = new Map(raw.map((v) => [v.id, v]));
  }, [raw]);

  useEffect(() => {
    const id = window.setInterval(() => {
      setSmoothed((prev) => {
        const next: TrainVehicle[] = [];
        const alpha = 0.14;
        for (const target of Array.from(targetsRef.current.values())) {
          const old = prev.find((p) => p.id === target.id);
          const from = old?.coordinates ?? target.coordinates;
          const t = target.coordinates;
          next.push({
            ...target,
            coordinates: [
              from[0] + (t[0] - from[0]) * alpha,
              from[1] + (t[1] - from[1]) * alpha,
            ],
          });
        }
        return next;
      });
    }, 50);
    return () => clearInterval(id);
  }, []);

  return smoothed;
}

const TrainsClusterLayers = memo(function TrainsClusterLayers({
  data,
}: {
  data: TrainFeatureCollection;
}) {
  return (
    <Source
      id="trains-source"
      type="geojson"
      data={data}
      cluster
      clusterMaxZoom={CLUSTER_MAX_ZOOM}
      clusterRadius={CLUSTER_RADIUS}
    >
      <Layer
        id="train-clusters"
        type="circle"
        filter={["has", "point_count"]}
        paint={{
          "circle-color": [
            "step",
            ["get", "point_count"],
            "#51bbd6",
            10,
            "#f1cb04",
            50,
            "#f28cb1",
          ],
          "circle-radius": ["step", ["get", "point_count"], 18, 10, 22, 50, 28],
        }}
      />
      <Layer
        id="train-cluster-count"
        type="symbol"
        filter={["has", "point_count"]}
        layout={{
          "text-field": "{point_count_abbreviated}",
          "text-size": 12,
        }}
        paint={{
          "text-color": "#ffffff",
        }}
      />
      <Layer
        id="train-unclustered"
        type="circle"
        filter={["!", ["has", "point_count"]]}
        paint={{
          "circle-color": ["get", "colour"],
          "circle-radius": 8,
          "circle-stroke-width": 1,
          "circle-stroke-color": "#ffffff",
        }}
      />
    </Source>
  );
});

export default function TrainMap() {
  const mapRef = useRef<MapLibreMap | null>(null);
  const boundsRef = useRef<ReturnType<MapLibreMap["getBounds"]> | null>(null);
  const pollTimer = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [rawTrains, setRawTrains] = useState<TrainVehicle[] | undefined>();
  const [loading, setLoading] = useState(true);
  const [zoom, setZoom] = useState<number>();
  const [lineFilter, setLineFilter] = useState("");
  const [selectedId, setSelectedId] = useState<number | undefined>();

  const smoothed = useSmoothedTrains(rawTrains);

  const filtered = useMemo(() => {
    if (!lineFilter) {
      return smoothed;
    }
    return smoothed.filter((v) => v.route_id === lineFilter);
  }, [smoothed, lineFilter]);

  const lineOptions = useMemo(() => {
    const s = new Set<string>();
    for (const v of rawTrains || []) {
      if (v.route_id) {
        s.add(v.route_id);
      }
    }
    return Array.from(s).sort();
  }, [rawTrains]);

  const clusterGeoJson = useMemo((): TrainFeatureCollection => {
    if (filtered.length < CLUSTER_THRESHOLD) {
      return { type: "FeatureCollection", features: [] };
    }
    return {
      type: "FeatureCollection",
      features: filtered.map((v) => ({
        type: "Feature" as const,
        id: v.id,
        geometry: {
          type: "Point" as const,
          coordinates: v.coordinates,
        },
        properties: {
          id: v.id,
          colour: v.vehicle?.colour || "#2d6a9f",
        },
      })),
    };
  }, [filtered]);

  const useClusterLayer = filtered.length >= CLUSTER_THRESHOLD;

  const trainsById = useMemo(() => {
    const m = new Map<number, TrainVehicle>();
    for (const v of filtered) {
      m.set(v.id, v);
    }
    return m;
  }, [filtered]);

  const loadTrains = useCallback((first = false) => {
    if (!first && document.hidden) {
      return;
    }
    if (pollTimer.current) {
      window.clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
    if (abortRef.current) {
      abortRef.current.abort();
    }
    const b = boundsRef.current;
    if (!b) {
      return;
    }
    const z = mapRef.current?.getZoom() ?? zoom ?? 0;
    if (z < MIN_ZOOM_TRAINS) {
      setRawTrains([]);
      setLoading(false);
      if (!document.hidden) {
        pollTimer.current = window.setTimeout(() => loadTrains(false), POLL_MS);
      }
      return;
    }
    const qs = getBoundsQueryString(b);
    abortRef.current = new AbortController();
    setLoading(true);
    fetch(`${trainsJsonUrl()}${qs}`, {
      credentials: "omit",
      signal: abortRef.current.signal,
    })
      .then((r) => (r.ok ? r.json() : { train_locations: [] }))
      .then((data: { train_locations: any[] }) => {
        // Transform transportstatistics.com format to TrainVehicle format
        const trains: TrainVehicle[] = data.train_locations.map((train: any, index: number) => ({
          id: parseInt(train.rid) || index,
          coordinates: [train.location.lon, train.location.lat],
          vehicle: {
            url: '',
            name: train.train_operator || 'Unknown',
            colour: '#2d6a9f',
          },
          route_id: train.headcode,
          datetime: train.ts || new Date().toISOString(),
          destination: train.destination?.name || '',
          // Additional train-specific fields
          operator: train.train_operator,
          delay: train.delay,
          origin: train.origin?.name,
          headcode: train.headcode,
          uid: train.uid,
          toc_code: train.toc_code,
          predicted_location: train.predicted_location,
          predicted_ts: train.predicted_ts,
        }));
        setRawTrains(trains);
        setLoading(false);
      })
      .catch(() => {
        setLoading(false);
      })
      .finally(() => {
        if (!document.hidden) {
          pollTimer.current = window.setTimeout(() => loadTrains(false), POLL_MS);
        }
      });
  }, []);

  const debouncedLoad = useMemo(
    () => debounce(() => loadTrains(false), 250),
    [loadTrains],
  );

  const handleMoveEnd = useCallback(
    (evt: ViewStateChangeEvent) => {
      boundsRef.current = evt.target.getBounds();
      setZoom(evt.target.getZoom());
      debouncedLoad();
    },
    [debouncedLoad],
  );

  const handleMapInit = useCallback(
    (map: MapLibreMap) => {
      mapRef.current = map;
      if (!boundsRef.current) {
        boundsRef.current = map.getBounds();
        setZoom(map.getZoom());
        loadTrains(true);
      }
    },
    [loadTrains],
  );

  useEffect(() => {
    const onVis = () => {
      if (!document.hidden) {
        loadTrains(false);
      }
    };
    window.addEventListener("visibilitychange", onVis);
    return () => {
      window.removeEventListener("visibilitychange", onVis);
      if (pollTimer.current) {
        window.clearTimeout(pollTimer.current);
      }
      if (abortRef.current) {
        abortRef.current.abort();
      }
      debouncedLoad.cancel();
    };
  }, [loadTrains, debouncedLoad]);

  const expandCluster = useCallback((e: MapLayerMouseEvent) => {
    const map = mapRef.current;
    const feature = e.features?.[0];
    if (!map || !feature?.properties) {
      return;
    }
    const isCluster = feature.properties.cluster;
    if (!isCluster) {
      return;
    }
    const clusterId = feature.properties.cluster_id as number;
    const src = map.getSource("trains-source") as GeoJSONSource | undefined;
    if (!src || typeof src.getClusterExpansionZoom !== "function") {
      return;
    }
    src
      .getClusterExpansionZoom(clusterId)
      .then((z: number) => {
        map.easeTo({
          center: (feature.geometry as GeoJSON.Point).coordinates as [
            number,
            number,
          ],
          zoom: z,
        });
      })
      .catch(() => undefined);
  }, []);

  const handleMapClick = useCallback(
    (e: MapLayerMouseEvent) => {
      const markerId = getClickedVehicleMarkerId(e);
      if (markerId != null) {
        setSelectedId(markerId);
        return;
      }
      for (const f of e.features || []) {
        if (f.layer.id === "train-clusters") {
          expandCluster(e);
          return;
        }
        if (f.layer.id === "train-unclustered" && f.properties?.id != null) {
          setSelectedId(Number(f.properties.id));
          return;
        }
      }
      setSelectedId(undefined);
    },
    [expandCluster],
  );

  const selectedVehicle = selectedId != null ? trainsById.get(selectedId) : undefined;

  useEffect(() => {
    document.title = "Train map \u2013 bustimes.org";
  }, []);

  const interactiveIds = useClusterLayer
    ? ["train-clusters", "train-unclustered"]
    : [];

  return (
    <React.Fragment>
      <Link className="map-link" href="/map">
        Bus map
      </Link>
      <div className="big-map train-map-wrap">
        <div className="train-map-toolbar maplibregl-ctrl maplibregl-ctrl-group">
          <label>
            Line{" "}
            <select
              value={lineFilter}
              onChange={(ev) => setLineFilter(ev.target.value)}
            >
              <option value="">All</option>
              {lineOptions.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
          </label>
        </div>
        <BusTimesMap
          initialViewState={window.INITIAL_VIEW_STATE}
          onMoveEnd={handleMoveEnd}
          hash
          onClick={handleMapClick}
          onMapInit={handleMapInit}
          interactiveLayerIds={interactiveIds}
        >
          {useClusterLayer ? (
            <TrainsClusterLayers data={clusterGeoJson} />
          ) : (
            filtered.map((v) => (
              <VehicleMarker
                key={v.id}
                vehicle={v}
                selected={v.id === selectedId}
              />
            ))
          )}
          {useClusterLayer && selectedVehicle ? (
            <VehicleMarker vehicle={selectedVehicle} selected />
          ) : null}
          {selectedVehicle ? (
            <VehiclePopup
              item={selectedVehicle}
              onClose={() => setSelectedId(undefined)}
            />
          ) : null}
          {zoom && zoom < 6 ? (
            <div className="maplibregl-ctrl map-status-bar">
              Zoom in to load trains in this area
            </div>
          ) : null}
          {loading && zoom && zoom >= 6 ? (
            <div className="maplibregl-ctrl map-status-bar">Loading trains…</div>
          ) : null}
        </BusTimesMap>
      </div>
    </React.Fragment>
  );
}
